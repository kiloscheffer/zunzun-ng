"""Tests for the per-session and per-IP concurrency caps.

MAX_CONCURRENT_FITS_PER_SESSION (default 1) and MAX_CONCURRENT_FITS_PER_IP
(default 4) gate new fit POSTs. The gate counts INITIALIZING/RUNNING rows with
a fresh (<300s) last_status_check heartbeat. Provably-dead rows (crashed child
whose heartbeat is still fresh) are finalized on-demand when a cap would
otherwise block, so a SIGKILL/OOM victim doesn't strand the session.
"""

import os
import time
from unittest import mock

import pytest


def _plant_status_row(client, **fields):
    """Create an LRPStatus row owned by the client's current session and point
    the session at it (the pk a prior dispatch would have left).

    The new gate counts by owner_session_key, so the row must carry the
    client's real session key.  If the caller doesn't supply owner_session_key
    explicitly, it is auto-filled from the client's active session.
    """
    from zunzun.models import LRPStatus

    session = client.session
    fields.setdefault("owner_session_key", session.session_key or "")
    fields.setdefault("owner_ip", "127.0.0.1")
    row = LRPStatus.objects.create(**fields)
    session["lrp_status_pk"] = row.pk
    session["cookie_test"] = 1
    session.save()
    return row


# ── Session cap: basic refuse / admit ───────────────────────────────────────


@pytest.mark.django_db
def test_concurrent_fit_refused_when_at_session_cap(client):
    """With MAX_CONCURRENT_FITS_PER_SESSION=1, a second POST is refused when
    there is already one RUNNING row with a fresh heartbeat for this session."""
    from zunzun.models import LRPStatus

    client.get("/")
    _plant_status_row(
        client,
        # Use the live test-process pid so the dead-child backstop sees a
        # genuine running fit (probe returns alive) and does not finalize it.
        process_id=os.getpid(),
        state=LRPStatus.State.RUNNING,
        last_status_check=time.time(),
    )

    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 1, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True):
            response = client.post(
                "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
                data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
            )
    assert b"already have a fit in progress" in response.content


@pytest.mark.django_db
def test_concurrent_fit_refused_for_running_fit_without_polling(client):
    """Regression guard for the non-polling client path.

    The dispatch stamps last_status_check at creation, so once the child writes
    process_id the heartbeat-freshness check (now - last_status_check < 300) holds
    for 300 s even if the client never polls (closed tab/script).  Models the
    steady state ~2 min into a running fit with no polling: start_time and
    last_status_check both at dispatch time (well within the 300 s window),
    process_id set, state RUNNING.
    """
    from zunzun.models import LRPStatus

    client.get("/")
    dispatch_time = time.time() - 120  # 2 min ago; never polled since
    _plant_status_row(
        client,
        process_id=os.getpid(),
        state=LRPStatus.State.RUNNING,
        start_time=dispatch_time,
        last_status_check=dispatch_time,
    )

    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 1, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True):
            response = client.post(
                "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
                data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
            )
    # Active fit, no polling → heartbeat still fresh (< 300 s) → REFUSED
    assert b"already have a fit in progress" in response.content


@pytest.mark.django_db
def test_concurrent_fit_refused_for_initializing_row(client):
    """An INITIALIZING row with a fresh heartbeat (double-click / fast
    re-submit before the child claims the row) blocks a second POST."""
    from zunzun.models import LRPStatus

    client.get("/")
    _plant_status_row(
        client,
        state=LRPStatus.State.INITIALIZING,
        process_id=0,
        start_time=time.time(),
        last_status_check=time.time(),
    )

    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 1, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True):
            response = client.post(
                "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
                data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
            )
    assert b"already have a fit in progress" in response.content


# ── Session cap: admit cases ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_concurrent_fit_admitted_under_session_cap(client, mocked_process_start):
    """Under the cap (0 active rows) a POST is admitted (no refuse response)."""
    client.get("/")
    # No planted row → per_session == 0 < cap → gate allows
    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 1, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True):
            response = client.post(
                "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
                data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
            )
    assert b"already have a fit in progress" not in response.content
    assert b"from your network" not in response.content


@pytest.mark.django_db
def test_concurrent_fit_admitted_after_stale_heartbeat(client, mocked_process_start):
    """A row whose last_status_check is >300 s old is NOT counted as active
    (matches CheckIfStillUsed's abandonment threshold) → gate allows."""
    from zunzun.models import LRPStatus

    client.get("/")
    _plant_status_row(
        client,
        process_id=12345,
        state=LRPStatus.State.RUNNING,
        last_status_check=time.time() - 400,
    )

    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 1, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True):
            response = client.post(
                "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
                data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
            )
    assert b"already have a fit in progress" not in response.content


@pytest.mark.django_db
def test_concurrent_fit_admitted_after_clean_completion(client, mocked_process_start):
    """A TERMINAL row (process_id=0, state=TERMINAL, recent heartbeat) is
    never counted — the gate excludes TERMINAL rows."""
    from zunzun.models import LRPStatus

    client.get("/")
    _plant_status_row(
        client,
        process_id=0,
        state=LRPStatus.State.TERMINAL,
        start_time=time.time() - 120,
        last_status_check=time.time(),
    )

    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 1, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True):
            response = client.post(
                "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
                data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
            )
    assert b"already have a fit in progress" not in response.content


@pytest.mark.django_db
def test_concurrent_fit_admitted_after_fast_completion(client, mocked_process_start):
    """A fit that completed in <60 s (start_time recent, state=TERMINAL) must
    not block the next POST."""
    from zunzun.models import LRPStatus

    client.get("/")
    _plant_status_row(
        client,
        process_id=0,
        state=LRPStatus.State.TERMINAL,
        start_time=time.time() - 30,
        last_status_check=time.time() - 5,
        redirect_to_results="/temp/abc.html",
    )

    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 1, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True):
            response = client.post(
                "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
                data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
            )
    assert b"already have a fit in progress" not in response.content


@pytest.mark.django_db
def test_concurrent_fit_admitted_after_fast_completion_redirect_consumed(
    client, mocked_process_start
):
    """Regression guard: StatusView clears redirect_to_results on serve.
    The post-consumption row (state=TERMINAL, redirect="", start_time recent)
    must still be admitted — TERMINAL excludes it from the count."""
    from zunzun.models import LRPStatus

    client.get("/")
    _plant_status_row(
        client,
        process_id=0,
        state=LRPStatus.State.TERMINAL,
        start_time=time.time() - 20,
        last_status_check=time.time() - 5,
        redirect_to_results="",
    )

    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 1, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True):
            response = client.post(
                "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
                data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
            )
    assert b"already have a fit in progress" not in response.content


# ── Dead-child probe-on-demand path ──────────────────────────────────────────


@pytest.mark.django_db
def test_dead_child_row_finalized_and_fit_admitted(client, monkeypatch, mocked_process_start):
    """Probe-on-demand path: a row whose child died WITHOUT finalizing
    (process_id set, state not TERMINAL, heartbeat fresh) must NOT block the
    user's retry.

    The gate calls _finalize_row_if_child_dead when a cap WOULD block, finds
    the pid gone, promotes the row to TERMINAL, recounts (per_session=0), and
    admits the new POST.  Without this path, a SIGKILL/OOM victim would strand
    the session for up to 300 s while the heartbeat ages out.
    """
    from zunzun.models import LRPStatus

    monkeypatch.setattr("zunzun.platform_compat.pid_is_alive", lambda pid: False)
    client.get("/")
    # Looks active (pid set, fresh heartbeat) but the owning child is dead.
    row_pk = _plant_status_row(
        client,
        process_id=4242,
        state=LRPStatus.State.RUNNING,
        start_time=time.time() - 30,
        last_status_check=time.time(),
    ).pk

    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 1, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True):
            response = client.post(
                "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
                data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
            )
    # Dead owner → backstop finalizes the row → gate must NOT block.
    assert b"already have a fit in progress" not in response.content
    assert b"from your network" not in response.content
    # Pin the mechanism, not just the outcome: the probe-on-demand path must
    # have promoted the dead row to TERMINAL (that's what cleared the count).
    row = LRPStatus.objects.get(pk=row_pk)
    assert row.state == LRPStatus.State.TERMINAL


# ── High-cap path: session cap doesn't block when under limit ────────────────


@pytest.mark.django_db
def test_session_cap_does_not_block_when_under_limit(client, mocked_process_start):
    """With MAX_CONCURRENT_FITS_PER_SESSION=2, a second POST from the same
    session while one fit is running must be admitted."""
    from zunzun.models import LRPStatus

    client.get("/")
    _plant_status_row(
        client,
        process_id=os.getpid(),
        state=LRPStatus.State.RUNNING,
        last_status_check=time.time(),
    )

    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 2, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True):
            response = client.post(
                "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
                data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
            )
    assert b"already have a fit in progress" not in response.content
    assert b"from your network" not in response.content


# ── Per-IP cap ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_per_ip_cap_refuses_when_at_limit(client):
    """Two rows from the same IP (different session keys) at
    MAX_CONCURRENT_FITS_PER_IP=1 → second POST refused with the 'from your
    network' message."""
    from zunzun.models import LRPStatus

    client.get("/")
    now = time.time()
    # Row from a DIFFERENT session (empty key) but same IP as the test client.
    LRPStatus.objects.create(
        start_time=now,
        last_status_check=now,
        owner_session_key="other-session",
        owner_ip="127.0.0.1",
        state=LRPStatus.State.RUNNING,
        process_id=os.getpid(),
    )
    session = client.session
    session["cookie_test"] = 1
    session.save()

    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 99, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 1, create=True):
            response = client.post(
                "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
                data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
            )
    assert b"from your network" in response.content


@pytest.mark.django_db
def test_per_ip_cap_admits_when_under_limit(client, mocked_process_start):
    """With MAX_CONCURRENT_FITS_PER_IP=2, a POST is admitted when only one
    active row exists for the IP."""
    from zunzun.models import LRPStatus

    client.get("/")
    now = time.time()
    LRPStatus.objects.create(
        start_time=now,
        last_status_check=now,
        owner_session_key="other-session",
        owner_ip="127.0.0.1",
        state=LRPStatus.State.RUNNING,
        process_id=os.getpid(),
    )
    session = client.session
    session["cookie_test"] = 1
    session.save()

    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 99, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 2, create=True):
            response = client.post(
                "/FitEquation__F__/2/Polynomial/Linear%20Polynomial/",
                data={"IndependentData": "1 2 3", "DependentData": "1 2 3"},
            )
    assert b"from your network" not in response.content
    assert b"already have a fit in progress" not in response.content


# ── Per-dispatch row preservation ────────────────────────────────────────────


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
    """Regression guard for the dispatch-time stamp: the LRPStatus row must be
    created with last_status_check == start_time (stamped at dispatch, not 0.0).

    This is what makes the heartbeat-freshness check in _active_fit_counts hold
    for 300 s without any polling.  If the stamp regresses, last_status_check
    stays 0.0 and a non-polling client bypasses the cap ~0.5 s after the child
    writes process_id.
    """
    from zunzun.models import LRPStatus

    client.get("/")
    session = client.session
    session["cookie_test"] = 1
    session.save()

    before = time.time()
    response = client.post(
        "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/",
        data=_VALID_2D_QUAD_FIELDS,
        HTTP_HOST="testserver",
    )
    after = time.time()
    assert response.status_code in (301, 302), (
        f"expected dispatch redirect, got {response.status_code}: {response.content[:300]!r}"
    )

    pk = client.session["lrp_status_pk"]
    row = LRPStatus.objects.get(pk=pk)
    assert row.last_status_check != 0.0
    assert before <= row.last_status_check <= after
    assert row.last_status_check == row.start_time


@pytest.mark.django_db
def test_dispatch_preserves_prior_row(client, mocked_process_start):
    """A new dispatch must NOT delete the user's prior LRPStatus row.

    Delete-prior-row is removed: every dispatch creates an independent row and
    leaves the prior row for the housekeeping age-sweep.  The prior fit keeps
    running because CheckIfStillUsed sees its row intact; only the session
    pointer moves to the new row.

    Replaces the old concurrent-allowed / concurrent-disallowed test pair that
    exercised the now-removed delete-prior-row code path.  The new invariant is
    unconditional: NO dispatch ever deletes a prior row.
    """
    from zunzun.models import LRPStatus

    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 99, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True):
            client.get("/")
            # Plant an ACTIVE prior fit (pid set, fresh heartbeat).
            old = _plant_status_row(
                client,
                process_id=4242,
                start_time=time.time() - 30,
                last_status_check=time.time(),
                current_status="prior fit running",
            )
            old_pk = old.pk

            response = client.post(
                "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/",
                data=_VALID_2D_QUAD_FIELDS,
                HTTP_HOST="testserver",
            )
            assert response.status_code in (301, 302), (
                f"expected dispatch redirect, got {response.status_code}: "
                f"{response.content[:300]!r}"
            )

            # The prior (still-running) row must SURVIVE — housekeeping, not
            # the dispatch path, reclaims it.
            assert LRPStatus.objects.filter(pk=old_pk).exists()
            # ...and the session now points at a DIFFERENT, fresh row.
            new_pk = client.session["lrp_status_pk"]
            assert new_pk != old_pk
            assert LRPStatus.objects.filter(pk=new_pk).exists()
