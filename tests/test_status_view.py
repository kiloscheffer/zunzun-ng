"""StatusView and StatusUpdateView tests.

Pins completion-branch behavior (file body serve, URL redirect, redirect
clearing) and the JSON polling endpoint, now backed by the per-dispatch
LRPStatus row (request.session['lrp_status_pk']) rather than the old
shared status session blob.
"""

import time

import pytest

import settings  # raw module — views.py uses `import settings` directly; patch here, not django.conf.settings


def _make_status_row(**kwargs):
    """Create a fresh LRPStatus row with provided field overrides and
    return it. Caller wires its pk into request.session['lrp_status_pk'].
    """
    from zunzun.models import LRPStatus

    return LRPStatus.objects.create(**kwargs)


def _wire_status_row(client, row):
    """Point the client's request session at the given LRPStatus row."""
    session = client.session
    session["lrp_status_pk"] = row.pk
    session.save()


@pytest.mark.django_db
def test_status_view_serves_file_body_on_completion(client, tmp_path, monkeypatch):
    """When redirect_to_results is a path inside TEMP_FILES_DIR, StatusView
    reads the file and returns its contents as the response body.
    """
    monkeypatch.setattr(settings, "TEMP_FILES_DIR", str(tmp_path))
    result_file = tmp_path / "result.html"
    result_file.write_text("<html><body>FAKE RESULT</body></html>")

    row = _make_status_row(redirect_to_results=str(result_file))
    _wire_status_row(client, row)

    response = client.get("/StatusAndResults/")
    assert response.status_code == 200
    assert b"FAKE RESULT" in response.content


@pytest.mark.django_db
def test_status_view_redirects_on_completion_url(client):
    """When redirect_to_results is a site-relative URL (does NOT start with
    TEMP_FILES_DIR), StatusView returns HttpResponseRedirect.
    """
    row = _make_status_row(redirect_to_results="/FunctionFinderResults/2/?RANK=1&unused=1")
    _wire_status_row(client, row)

    response = client.get("/StatusAndResults/")
    assert response.status_code == 302
    assert response.url == "/FunctionFinderResults/2/?RANK=1&unused=1"


@pytest.mark.django_db
def test_status_view_clears_redirect_after_consuming(client):
    """StatusView must clear redirect_to_results after using it, so a
    subsequent GET to /StatusAndResults/ does not re-fire the redirect.
    """
    from zunzun.models import LRPStatus

    row = _make_status_row(redirect_to_results="/FunctionFinderResults/2/?RANK=1&unused=1")
    _wire_status_row(client, row)

    client.get("/StatusAndResults/")

    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert reloaded.redirect_to_results == ""


@pytest.mark.django_db
def test_status_update_returns_in_progress_json(client):
    row = _make_status_row(
        current_status="Calculating Error Statistics",
        start_time=time.time() - 84.0,
        last_status_check=time.time() - 2.0,
    )
    _wire_status_row(client, row)

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
    """When redirect_to_results is set, the poll endpoint reports completion
    and does NOT clear the redirect — clearing is owned by StatusView.
    """
    from zunzun.models import LRPStatus

    row = _make_status_row(
        current_status="done",
        start_time=time.time(),
        last_status_check=time.time(),
        redirect_to_results="/FunctionFinderResults/2/?RANK=1&unused=1",
    )
    _wire_status_row(client, row)

    response = client.get("/StatusUpdate/")
    assert response.status_code == 200
    assert response.json() == {"completed": True}

    # Redirect must NOT be cleared by the polling endpoint.
    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert reloaded.redirect_to_results == "/FunctionFinderResults/2/?RANK=1&unused=1"


@pytest.mark.django_db
def test_status_update_updates_heartbeat(client):
    from zunzun.models import LRPStatus

    row = _make_status_row(
        current_status="working",
        start_time=time.time() - 10.0,
        last_status_check=time.time() - 1.0,
    )
    _wire_status_row(client, row)

    before = time.time()
    client.get("/StatusUpdate/")
    after = time.time()

    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert before <= reloaded.last_status_check <= after


@pytest.mark.django_db
def test_status_update_400_when_pk_missing(client):
    """No lrp_status_pk on the request session -> 400 stale_session."""
    response = client.get("/StatusUpdate/")
    assert response.status_code == 400
    assert response.json() == {"error": "stale_session"}


@pytest.mark.django_db
def test_status_update_400_when_row_deleted(client):
    """lrp_status_pk present but the row no longer exists -> stale_session 400."""
    from zunzun.models import LRPStatus

    row = _make_status_row(current_status="working", start_time=time.time())
    _wire_status_row(client, row)
    LRPStatus.objects.filter(pk=row.pk).delete()

    response = client.get("/StatusUpdate/")
    assert response.status_code == 400
    assert response.json() == {"error": "stale_session"}


@pytest.mark.django_db
def test_status_view_renders_template_when_in_progress(client):
    """When no redirect is set, StatusView renders the status.html template
    with the expected DOM markers the JS will target.
    """
    row = _make_status_row(
        current_status="Calculating Error Statistics",
        start_time=time.time() - 30.0,
        last_status_check=time.time() - 1.0,
    )
    _wire_status_row(client, row)

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
    # The current_status value from the row must be rendered into the initial frame.
    assert "Calculating Error Statistics" in body


@pytest.mark.django_db
def test_status_view_extends_generic_template(client):
    """Initial render should carry the site chrome (header logo, footer, css)."""
    row = _make_status_row(current_status="working", start_time=time.time())
    _wire_status_row(client, row)

    body = client.get("/StatusAndResults/").content.decode("utf-8")
    assert "small_logo.png" in body  # header logo from generic template
    assert "custom.css" in body  # site CSS
    assert "FindCurves" in body  # footer link


@pytest.mark.django_db
def test_status_view_does_not_write_heartbeat(client):
    """Heartbeat write moved to StatusUpdateView; StatusView's initial render
    must NOT update last_status_check.
    """
    from zunzun.models import LRPStatus

    row = _make_status_row(
        current_status="working",
        start_time=time.time(),
        last_status_check=0.0,  # sentinel
    )
    _wire_status_row(client, row)

    client.get("/StatusAndResults/")

    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert reloaded.last_status_check == 0.0


@pytest.mark.django_db
def test_status_view_message_when_no_row(client):
    """If there is no lrp_status_pk / row, StatusView returns a user-visible
    'could not read your session data' message (200 body).
    """
    response = client.get("/StatusAndResults/")
    assert response.status_code == 200
    assert b"session data" in response.content


@pytest.mark.django_db
def test_status_update_returns_completed_when_completed_flag_set_without_redirect(client):
    """A terminal fit with completed=True but an EMPTY redirect (a mid-fit
    crash whose error page could not be linked, or a success already served &
    cleared in another tab) must still report completion so the poller stops.

    Regression: the endpoint used to key completion only off
    redirect_to_results, so this state reported completed=False forever and the
    status page heartbeated indefinitely.
    """
    row = _make_status_row(
        current_status="An unknown exception has occurred.",
        start_time=time.time(),
        last_status_check=time.time(),
        completed=True,
        redirect_to_results="",
    )
    _wire_status_row(client, row)

    response = client.get("/StatusUpdate/")
    assert response.status_code == 200
    assert response.json() == {"completed": True}


@pytest.mark.django_db
def test_status_view_serves_terminal_page_when_completed_without_redirect(client):
    """When completed=True but the redirect is empty, StatusView must serve a
    terminal page rather than the in-progress status template (which re-arms
    the JS poll loop). Without this the browser bounces between StatusUpdate
    (now reporting completed) and StatusView (re-rendering the working page)
    forever.
    """
    row = _make_status_row(
        current_status="An unknown exception has occurred.",
        start_time=time.time(),
        last_status_check=time.time(),
        completed=True,
        redirect_to_results="",
    )
    _wire_status_row(client, row)

    response = client.get("/StatusAndResults/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    # Terminal page, not the polling page: the poll script must be absent so
    # the browser does not re-enter the status loop.
    assert "StatusPoll.js" not in body
    assert "no results to display" in body
