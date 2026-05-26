"""StatusView and StatusUpdateView tests.

Pins existing completion-branch behavior (file body serve, URL redirect,
key clearing) and exercises the new JSON polling endpoint.
"""
import os
import time

import pytest
from django.contrib.sessions.backends.db import SessionStore

import settings


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
