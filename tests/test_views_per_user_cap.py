"""Tests for the ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER setting.

When False, a second fit POST is refused with an in-progress HTML message
if the user's status session shows an active fit within the last 60s.
"""

import time
from unittest import mock

import pytest


@pytest.mark.django_db
def test_concurrent_fit_allowed_when_flag_true(client, mocked_process_start):
    """Default (True) — second POST proceeds even with an active processID."""
    from django.contrib.sessions.backends.db import SessionStore

    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", True, create=True):
        client.get("/")  # bootstrap session
        # Plant an active processID in the status session
        s = SessionStore()
        s["processID"] = 12345
        s["time_of_last_status_check"] = time.time()
        s.save()
        session = client.session
        session["session_key_status"] = s.session_key
        session["cookie_test"] = 1
        session.save()

        # POST should proceed past the per-user gate (form may still fail
        # downstream — we only care that "already in progress" is NOT the
        # response, which would mean the gate did fire).
        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        assert b"already in progress" not in response.content


@pytest.mark.django_db
def test_concurrent_fit_refused_when_flag_false_and_recent_fit(client):
    """ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=False — refuse second POST."""
    from django.contrib.sessions.backends.db import SessionStore

    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        # Manually plant a session_key_status with an active processID
        s = SessionStore()
        s["processID"] = 99999
        s["time_of_last_status_check"] = time.time()
        s.save()
        session = client.session
        session["session_key_status"] = s.session_key
        session["cookie_test"] = 1
        session.save()

        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        # Expect the "fit in progress" HTML body
        assert b"already in progress" in response.content


@pytest.mark.django_db
def test_concurrent_fit_allowed_when_stale_processID(client, mocked_process_start):
    """ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=False — but the previous fit
    is stale (last status check >60s ago) → allow."""
    from django.contrib.sessions.backends.db import SessionStore

    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        s = SessionStore()
        s["processID"] = 12345
        s["time_of_last_status_check"] = time.time() - 120  # 2 minutes ago
        s.save()
        session = client.session
        session["session_key_status"] = s.session_key
        session["cookie_test"] = 1
        session.save()

        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        # Stale → should proceed past the per-user gate
        assert b"already in progress" not in response.content
