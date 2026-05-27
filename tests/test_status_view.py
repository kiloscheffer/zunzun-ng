"""StatusView and StatusUpdateView tests.

Pins existing completion-branch behavior (file body serve, URL redirect,
key clearing) and exercises the new JSON polling endpoint.
"""

import os
import time

import pytest
from django.contrib.sessions.backends.db import SessionStore

import settings  # raw module — views.py uses `import settings` directly; patch here, not django.conf.settings


def _make_status_session(**kwargs):
    """Create a fresh status SessionStore with provided keys set, save, and
    return it. Caller wires its session_key into request.session.
    """
    s = SessionStore()
    s.create()
    for k, v in kwargs.items():
        s[k] = v
    s.save()
    return s


def _wire_status_session(client, status_session):
    """Set session_key_status on the client's request session so the view
    can find the status SessionStore.
    """
    session = client.session
    session["session_key_status"] = status_session.session_key
    session.save()


@pytest.mark.django_db
def test_status_view_serves_file_body_on_completion(client, tmp_path, monkeypatch):
    """When redirectToResultsFileOrURL is a path inside TEMP_FILES_DIR,
    StatusView reads the file and returns its contents as the response body.
    """
    monkeypatch.setattr(settings, "TEMP_FILES_DIR", str(tmp_path))
    result_file = tmp_path / "result.html"
    result_file.write_text("<html><body>FAKE RESULT</body></html>")

    status_session = _make_status_session(
        redirectToResultsFileOrURL=str(result_file),
    )
    _wire_status_session(client, status_session)

    response = client.get("/StatusAndResults/")
    assert response.status_code == 200
    assert b"FAKE RESULT" in response.content


@pytest.mark.django_db
def test_status_view_redirects_on_completion_url(client):
    """When redirectToResultsFileOrURL is a site-relative URL (does NOT
    start with TEMP_FILES_DIR), StatusView returns HttpResponseRedirect.
    """
    status_session = _make_status_session(
        redirectToResultsFileOrURL="/FunctionFinderResults/2/?RANK=1&unused=1",
    )
    _wire_status_session(client, status_session)

    response = client.get("/StatusAndResults/")
    assert response.status_code == 302
    assert response.url == "/FunctionFinderResults/2/?RANK=1&unused=1"


@pytest.mark.django_db
def test_status_view_clears_redirect_key_after_consuming(client):
    """StatusView must clear redirectToResultsFileOrURL after using it,
    so a subsequent GET to /StatusAndResults/ does not re-fire the redirect.
    """
    status_session = _make_status_session(
        redirectToResultsFileOrURL="/FunctionFinderResults/2/?RANK=1&unused=1",
    )
    _wire_status_session(client, status_session)

    client.get("/StatusAndResults/")

    # Reload the status session from the DB to see the cleared state.
    reloaded = SessionStore(status_session.session_key)
    assert reloaded["redirectToResultsFileOrURL"] == ""


@pytest.mark.django_db
def test_status_update_returns_in_progress_json(client):
    status_session = _make_status_session(
        currentStatus="Calculating Error Statistics",
        start_time=time.time() - 84.0,
        timestamp=time.time() - 2.0,
    )
    _wire_status_session(client, status_session)

    response = client.get("/StatusUpdate/")
    assert response.status_code == 200
    data = response.json()
    assert data["completed"] is False
    assert data["currentStatus"] == "Calculating Error Statistics"
    assert data["elapsed"] in ("00:01:24", "00:01:25")  # 84s offset ±1s for wall-clock race
    assert isinstance(data["loadavg"], list)
    assert len(data["loadavg"]) == 3
    # serverTime / lastUpdate are intentionally NOT in the contract — see commit msg.
    assert "serverTime" not in data
    assert "lastUpdate" not in data


@pytest.mark.django_db
def test_status_update_returns_completed_when_redirect_set(client):
    """When redirectToResultsFileOrURL is set, the poll endpoint reports
    completion and does NOT clear the key — clearing is owned by StatusView.
    """
    status_session = _make_status_session(
        currentStatus="done",
        start_time=time.time(),
        timestamp=time.time(),
        redirectToResultsFileOrURL="/FunctionFinderResults/2/?RANK=1&unused=1",
    )
    _wire_status_session(client, status_session)

    response = client.get("/StatusUpdate/")
    assert response.status_code == 200
    assert response.json() == {"completed": True}

    # Key must NOT be cleared by the polling endpoint.
    reloaded = SessionStore(status_session.session_key)
    assert reloaded["redirectToResultsFileOrURL"] == "/FunctionFinderResults/2/?RANK=1&unused=1"


@pytest.mark.django_db
def test_status_update_updates_heartbeat(client):
    status_session = _make_status_session(
        currentStatus="working",
        start_time=time.time() - 10.0,
        timestamp=time.time() - 1.0,
    )
    _wire_status_session(client, status_session)

    before = time.time()
    client.get("/StatusUpdate/")
    after = time.time()

    reloaded = SessionStore(status_session.session_key)
    assert before <= reloaded["time_of_last_status_check"] <= after


@pytest.mark.django_db
def test_status_update_400_when_session_missing(client):
    """No session_key_status on the request session -> 400 with no_session."""
    response = client.get("/StatusUpdate/")
    assert response.status_code == 400
    assert response.json() == {"error": "no_session"}


@pytest.mark.django_db
def test_status_update_400_when_required_keys_missing(client):
    """session_key_status present but the status session has no
    currentStatus/start_time -> stale_session 400. (timestamp used to be
    required but the view no longer reads it.)
    """
    status_session = _make_status_session()  # empty
    _wire_status_session(client, status_session)

    response = client.get("/StatusUpdate/")
    assert response.status_code == 400
    assert response.json() == {"error": "stale_session"}


@pytest.mark.django_db
def test_status_view_renders_template_when_in_progress(client):
    """When no redirect is set, StatusView renders the status.html template
    with the expected DOM markers the JS will target.
    """
    status_session = _make_status_session(
        currentStatus="Calculating Error Statistics",
        start_time=time.time() - 30.0,
        timestamp=time.time() - 1.0,
    )
    _wire_status_session(client, status_session)

    response = client.get("/StatusAndResults/")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")

    body = response.content.decode("utf-8")
    # JS-targeted element IDs must be present.
    assert 'id="currentStatus"' in body
    assert 'id="elapsedTime"' in body
    assert 'id="load1"' in body
    assert 'id="load5"' in body
    assert 'id="load15"' in body
    # serverTime / lastUpdate were dropped as redundant; ensure they stay gone.
    assert 'id="serverTime"' not in body
    assert 'id="lastUpdate"' not in body
    # The poll script must be included.
    assert "StatusPoll.js" in body
    # The currentStatus value from the session must be rendered into the initial frame.
    assert "Calculating Error Statistics" in body


@pytest.mark.django_db
def test_status_view_extends_generic_template(client):
    """Initial render should carry the site chrome (header logo, footer, css)."""
    status_session = _make_status_session(
        currentStatus="working",
        start_time=time.time(),
        timestamp=time.time(),
    )
    _wire_status_session(client, status_session)

    body = client.get("/StatusAndResults/").content.decode("utf-8")
    assert "small_logo.png" in body  # header logo from generic template
    assert "custom.css" in body  # site CSS
    assert "FindCurves" in body  # footer link


@pytest.mark.django_db
def test_status_view_does_not_write_heartbeat(client):
    """Heartbeat write moved to StatusUpdateView; StatusView's initial render
    must NOT update time_of_last_status_check.
    """
    status_session = _make_status_session(
        currentStatus="working",
        start_time=time.time(),
        timestamp=time.time(),
        time_of_last_status_check=0.0,  # sentinel
    )
    _wire_status_session(client, status_session)

    client.get("/StatusAndResults/")

    reloaded = SessionStore(status_session.session_key)
    assert reloaded["time_of_last_status_check"] == 0.0


@pytest.mark.django_db
def test_status_view_400_when_required_keys_missing(client):
    """If currentStatus/start_time/timestamp are missing, StatusView returns
    a user-visible 'delete your cookie' message (unchanged behavior).
    """
    status_session = _make_status_session()  # empty
    _wire_status_session(client, status_session)

    response = client.get("/StatusAndResults/")
    # Existing behavior is HttpResponse(str), which is 200 with an error message body.
    assert response.status_code == 200
    assert b"stale browser cookie" in response.content or b"session data" in response.content
