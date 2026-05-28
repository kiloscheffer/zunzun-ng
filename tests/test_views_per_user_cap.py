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
    is stale (last status check >300s ago, matching CheckIfStillUsed's
    abandoned-fit threshold) → allow."""
    from django.contrib.sessions.backends.db import SessionStore

    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        s = SessionStore()
        s["processID"] = 12345
        s["time_of_last_status_check"] = time.time() - 400  # ~7 minutes ago (> 300s threshold)
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


@pytest.mark.django_db
def test_concurrent_fit_allowed_after_clean_completion(client, mocked_process_start):
    """ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=False — after a fit completes
    cleanly, processID should have been reset to 0 by PerformAllWork's exit
    path. The next POST must not be blocked."""
    from django.contrib.sessions.backends.db import SessionStore

    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        # Simulate the state AFTER a successful fit: processID was set during
        # the fit then explicitly reset to 0 in PerformAllWork's tail.
        # time_of_last_status_check is still recent (final JS poll).
        s = SessionStore()
        s["processID"] = 0  # cleared by base PerformAllWork on success
        s["time_of_last_status_check"] = time.time()  # final poll was just now
        s.save()
        session = client.session
        session["session_key_status"] = s.session_key
        session["cookie_test"] = 1
        session.save()

        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        # No active fit (processID=0) → gate must NOT trigger
        assert b"already in progress" not in response.content


@pytest.mark.django_db
def test_concurrent_fit_refused_in_pending_window_before_child_writes_pid(client):
    """ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=False — between
    SetInitialStatusDataIntoSessionVariables (which writes start_time
    and time_of_last_status_check but NOT processID) and the child's
    first PerformAllWork status write (which writes processID), the
    status session has a fresh heartbeat but processID=0. A rapid
    double-submit in this window must still be refused."""
    from django.contrib.sessions.backends.db import SessionStore

    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        # Simulate the pending window: start_time and last_check are fresh
        # (parent just dispatched a fit), but processID is still 0 (child
        # hasn't yet written its PID).
        s = SessionStore()
        s["start_time"] = time.time()
        s["dispatched_at"] = time.time()  # gate now checks dispatched_at
        s["time_of_last_status_check"] = time.time()
        # processID intentionally NOT set (defaults to absent / 0)
        s.save()
        session = client.session
        session["session_key_status"] = s.session_key
        session["cookie_test"] = 1
        session.save()

        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        # Pending state → gate must block
        assert b"already in progress" in response.content


@pytest.mark.django_db
def test_concurrent_fit_allowed_after_fast_completion(client, mocked_process_start):
    """ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=False — a fit that completes
    in <60s clears dispatched_at and processID. The user's immediate next
    POST must NOT be blocked even though start_time is still recent."""
    from django.contrib.sessions.backends.db import SessionStore

    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        # Simulate state immediately after a fast successful fit:
        # processID and dispatched_at both cleared, but start_time still
        # holds the fit's start (a recent value).
        s = SessionStore()
        s["start_time"] = time.time() - 30  # fit started 30s ago
        s["time_of_last_status_check"] = time.time() - 5  # final poll 5s ago
        s["processID"] = 0  # cleared by PerformAllWork on success
        s["dispatched_at"] = 0  # cleared by PerformAllWork on success
        s.save()
        session = client.session
        session["session_key_status"] = s.session_key
        session["cookie_test"] = 1
        session.save()

        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        # Completed fit → both pending and active checks must NOT trigger
        assert b"already in progress" not in response.content
