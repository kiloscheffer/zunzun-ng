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
    assert data["elapsed"] == "00:01:24"
    assert "serverTime" in data
    assert "lastUpdate" in data
    assert isinstance(data["loadavg"], list)
    assert len(data["loadavg"]) == 3


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
    currentStatus/start_time/timestamp -> stale_session 400.
    """
    status_session = _make_status_session()  # empty
    _wire_status_session(client, status_session)

    response = client.get("/StatusUpdate/")
    assert response.status_code == 400
    assert response.json() == {"error": "stale_session"}
