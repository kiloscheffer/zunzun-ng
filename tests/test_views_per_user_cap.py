"""Tests for the ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER setting.

When False, a second fit POST is refused with an in-progress HTML message
if the user's prior LRPStatus row shows an active or pending fit. The gate
reads the row pointed at by request.session['lrp_status_pk'].
"""

import time
from unittest import mock

import pytest


def _plant_status_row(client, **fields):
    """Create an LRPStatus row with the given fields and point the client's
    request session at it (the pk a PRIOR dispatch would have left)."""
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(**fields)
    session = client.session
    session["lrp_status_pk"] = row.pk
    session["cookie_test"] = 1
    session.save()
    return row


@pytest.mark.django_db
def test_concurrent_fit_allowed_when_flag_true(client, mocked_process_start):
    """Default (True) — second POST proceeds even with an active process_id."""
    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", True, create=True):
        client.get("/")  # bootstrap session
        _plant_status_row(client, process_id=12345, last_status_check=time.time())

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
    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        _plant_status_row(client, process_id=99999, last_status_check=time.time())

        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        # Expect the "fit in progress" HTML body
        assert b"already in progress" in response.content


@pytest.mark.django_db
def test_concurrent_fit_allowed_when_stale_process_id(client, mocked_process_start):
    """ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=False — but the previous fit
    is stale (last status check >300s ago, matching CheckIfStillUsed's
    abandoned-fit threshold) → allow."""
    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        # last_status_check ~7 minutes ago (> 300s threshold)
        _plant_status_row(client, process_id=12345, last_status_check=time.time() - 400)

        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        # Stale → should proceed past the per-user gate
        assert b"already in progress" not in response.content


@pytest.mark.django_db
def test_concurrent_fit_allowed_after_clean_completion(client, mocked_process_start):
    """ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=False — after a fit completes
    cleanly, process_id is reset to 0 by PerformAllWork's exit path. The next
    POST must not be blocked."""
    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        # Simulate the state AFTER a successful fit: process_id was set during
        # the fit then explicitly reset to 0 in PerformAllWork's tail.
        # last_status_check is still recent (final JS poll). start_time is
        # old enough that the pending window has elapsed too.
        _plant_status_row(
            client,
            process_id=0,
            start_time=time.time() - 120,
            last_status_check=time.time(),
        )

        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        # No active fit (process_id=0, not pending) → gate must NOT trigger
        assert b"already in progress" not in response.content


@pytest.mark.django_db
def test_concurrent_fit_refused_in_pending_window_before_child_writes_pid(client):
    """ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=False — between the parent
    creating the row (fresh start_time, process_id=0, no redirect) and the
    child's first PerformAllWork status write (which writes process_id), the
    row shows a fresh start_time but process_id=0. A rapid double-submit in
    this window must still be refused."""
    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        # Pending window: start_time fresh (parent just dispatched), process_id
        # still 0 (child hasn't written its PID), no terminal redirect yet.
        _plant_status_row(
            client,
            process_id=0,
            start_time=time.time(),
            last_status_check=time.time(),
        )

        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        # Pending state → gate must block
        assert b"already in progress" in response.content


@pytest.mark.django_db
def test_concurrent_fit_allowed_after_fast_completion(client, mocked_process_start):
    """ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=False — a fit that completes
    in <60s sets redirect_to_results (the terminal "done" signal). Even
    though start_time is still recent, the next POST must NOT be blocked:
    the completed row is excluded from the pending check."""
    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        # State immediately after a fast successful fit: process_id cleared,
        # terminal redirect set, but start_time still recent (<60s).
        _plant_status_row(
            client,
            process_id=0,
            start_time=time.time() - 30,
            last_status_check=time.time() - 5,
            redirect_to_results="/temp/abc.html",
        )

        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        # Completed fit → neither pending nor active → gate must NOT trigger
        assert b"already in progress" not in response.content
