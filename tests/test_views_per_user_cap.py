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
def test_concurrent_fit_refused_for_active_fit_without_polling(client):
    """ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=False — regression guard for
    the non-polling client. Production stamps last_status_check at dispatch
    (LongRunningProcessView creates the row with last_status_check=now), so
    once the child writes process_id, is_active = process_id and
    (now - last_status_check) < 300 stays True for 300s even if the client
    NEVER polls (closed tab / script). Without the dispatch-time stamp,
    last_status_check would be 0.0, (now - 0.0) would exceed 300, and a
    second POST would slip through ~0.5s after dispatch.

    Models the steady state ~2 minutes into a running fit with no polling:
    start_time and last_status_check both at dispatch time (well past the
    60s pending window, well within the 300s active window), process_id set.
    """
    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        dispatch_time = time.time() - 120  # 2 min ago; never polled since
        _plant_status_row(
            client,
            process_id=54321,
            start_time=dispatch_time,
            last_status_check=dispatch_time,
        )

        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        # Active fit, no polling → is_active must still hold → REFUSED
        assert b"already in progress" in response.content


# Complete, valid 2D polynomial-quadratic form payload — enough for
# LongRunningProcessView to validate the form, transfer data, create the
# LRPStatus row, and reach the dispatch redirect. Mirrors the smoke test's
# _POLY_QUAD_FIELDS so the dispatch path is genuinely exercised.
_VALID_2D_QUAD_FIELDS = {
    "commaConversion": "I",
    "graphSize": "320x240",
    "animationSize": "0x0",
    "scientificNotationX": "AUTO",
    "scientificNotationY": "AUTO",
    "dataNameX": "X Data",
    "dataNameY": "Y Data",
    "graphScaleRadioButtonX": "0.050",
    "graphScaleRadioButtonY": "0.050",
    "logLinX": "LIN",
    "logLinY": "LIN",
    "logLinZ": "LIN",
    "fittingTarget": "SSQABS",
    "textDataEditor": "1 1\n2 4\n3 9\n4 16\n5 25\n6 36\n",
}


@pytest.mark.django_db
def test_dispatch_stamps_last_status_check_at_creation(client, mocked_process_start):
    """Regression guard for the actual one-line views.py fix: the dispatch
    path (LongRunningProcessView) must create the LRPStatus row with
    last_status_check stamped at dispatch, not left at the 0.0 default.

    This is what makes the per-user is_active check
    (process_id and (now - last_status_check) < 300) hold for 300s without
    polling. If the stamp regresses, last_status_check stays 0.0 and the
    cap leaks for non-polling clients ~0.5s after the child writes
    process_id. Drives a real (mocked-spawn) successful POST and inspects
    the row the view created.
    """
    from zunzun.models import LRPStatus

    client.get("/")  # bootstrap session + cookie_test
    session = client.session
    session["cookie_test"] = 1
    session.save()

    before = time.time()
    response = client.post(
        "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/",
        data=_VALID_2D_QUAD_FIELDS,
        HTTP_HOST="testserver",  # view builds the redirect from request.META["HTTP_HOST"]
    )
    after = time.time()
    # A valid POST dispatches (redirect to the status page).
    assert response.status_code in (301, 302), (
        f"expected dispatch redirect, got {response.status_code}: {response.content[:300]!r}"
    )

    pk = client.session["lrp_status_pk"]
    row = LRPStatus.objects.get(pk=pk)
    # last_status_check must be stamped at dispatch (≈ start_time), NOT 0.0.
    assert row.last_status_check != 0.0
    assert before <= row.last_status_check <= after
    # And it tracks start_time (both stamped from the same `now`).
    assert row.last_status_check == row.start_time


@pytest.mark.django_db
def test_dispatch_deletes_prior_status_row(client, mocked_process_start):
    """Row-reclamation guard: a new dispatch must delete the user's PRIOR
    LRPStatus row and repoint request.session['lrp_status_pk'] at a fresh
    row. This pins the delete-prior-row mechanism in LongRunningProcessView
    (old_pk = request.session.get('lrp_status_pk'); if old_pk:
    LRPStatus.objects.filter(pk=old_pk).delete()) — without it, superseded
    rows would accumulate unbounded between housekeeping sweeps.

    Default (concurrent-allowed) config so the per-user gate doesn't
    short-circuit before the create/delete block runs.
    """
    from zunzun.models import LRPStatus

    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", True, create=True):
        client.get("/")  # bootstrap session
        # Plant a prior row and point the session at it (as a previous
        # dispatch would have left it).
        old = _plant_status_row(client, start_time=time.time() - 100, current_status="prior fit")
        old_pk = old.pk

        response = client.post(
            "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/",
            data=_VALID_2D_QUAD_FIELDS,
            HTTP_HOST="testserver",
        )
        assert response.status_code in (301, 302), (
            f"expected dispatch redirect, got {response.status_code}: {response.content[:300]!r}"
        )

        # The prior row was deleted...
        assert not LRPStatus.objects.filter(pk=old_pk).exists()
        # ...and the session now points at a DIFFERENT, existing row.
        new_pk = client.session["lrp_status_pk"]
        assert new_pk != old_pk
        assert LRPStatus.objects.filter(pk=new_pk).exists()


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
    in <60s sets completed=True (the terminal "done" signal). Even though
    start_time is still recent and redirect_to_results is still present (not
    yet consumed by StatusView), the next POST must NOT be blocked: the
    completed row is excluded from the pending check."""
    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        # State immediately after a fast successful fit: process_id cleared,
        # completed set, terminal redirect set, start_time still recent (<60s).
        _plant_status_row(
            client,
            process_id=0,
            completed=True,
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


@pytest.mark.django_db
def test_concurrent_fit_allowed_after_fast_completion_when_redirect_consumed(
    client, mocked_process_start
):
    """Regression guard for the redirect-overload bug: StatusView clears
    redirect_to_results the moment it serves the result. For a fast fit the
    user views within 60s of dispatch, the post-consumption row is:
        completed=True, process_id=0, redirect_to_results="", start_time recent
    The old gate (which keyed the pending window on `not redirect_to_results`)
    would see an empty redirect + recent start_time + no process_id and
    re-block the next POST for the rest of the 60s window. With the explicit
    `completed` flag the gate must allow the re-submit.

    Fails on the pre-fix code (redirect-clause gate); passes with the flag.
    """
    with mock.patch("settings.ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", False, create=True):
        client.get("/")
        _plant_status_row(
            client,
            process_id=0,
            completed=True,
            start_time=time.time() - 20,  # within the 60s pending window
            last_status_check=time.time() - 5,
            redirect_to_results="",  # StatusView already consumed it
        )

        response = client.post(
            "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
            data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
        )
        # Completed (flag set) → gate must NOT block even though redirect was
        # consumed and start_time is still inside the pending window.
        assert b"already in progress" not in response.content
