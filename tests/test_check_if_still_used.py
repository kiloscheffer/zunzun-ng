"""Tests for StatusMonitoredLongRunningProcessPage.CheckIfStillUsed.

CheckIfStillUsed is the abandoned-fit watchdog the spawned child runs once
per second (via _oneSecondStatusUpdate). It reads this dispatch's LRPStatus
row and tears down the fit pool + terminates worker children when EITHER:
  - a different (foreign) process_id appears in the row (a newer fit took
    over this user's session under the concurrent-disallowed config), OR
  - the heartbeat (last_status_check, falling back to start_time) is stale
    (> 300s), meaning the client stopped polling and the fit was abandoned.

The critical invariant exercised here: a never-polled but still-live fit
(own pid, last_status_check still at its dispatch stamp) must NOT be killed.
"""

import os
import time
from unittest import mock

import pytest


def _make_lrp(status_row_pk):
    """Build a base LRP with a Mock fit_pool and the given status_row_pk.
    Returns (lrp, fit_pool_mock)."""
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
    )

    lrp = StatusMonitoredLongRunningProcessPage()
    lrp.status_row_pk = status_row_pk
    fit_pool = mock.Mock()
    lrp.fit_pool = fit_pool
    return lrp, fit_pool


def _run_check(lrp):
    """Run CheckIfStillUsed with time.sleep and active_children patched out
    so the test is fast and doesn't touch real OS children."""
    with (
        mock.patch("time.sleep"),
        mock.patch(
            "zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage.multiprocessing.active_children",
            return_value=[],
        ),
    ):
        lrp.CheckIfStillUsed()


@pytest.mark.django_db
def test_never_polled_own_pid_does_not_teardown():
    """Own pid, last_status_check=0.0 (never polled), start_time recent →
    the start_time fallback keeps (now - last_check) under 300s, so the live
    fit must NOT self-terminate. fit_pool stays intact."""
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(
        process_id=os.getpid(),
        last_status_check=0.0,
        start_time=time.time(),
    )
    lrp, fit_pool = _make_lrp(row.pk)

    _run_check(lrp)

    fit_pool.shutdown.assert_not_called()
    assert lrp.fit_pool is fit_pool  # not torn down


@pytest.mark.django_db
def test_foreign_pid_tears_down():
    """A different process_id in the row (a newer fit claimed the session) →
    this older fit is abandoned and must tear its pool down."""
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(
        process_id=os.getpid() + 1,  # not this process
        last_status_check=time.time(),  # fresh heartbeat, so only the pid path fires
        start_time=time.time(),
    )
    lrp, fit_pool = _make_lrp(row.pk)

    _run_check(lrp)

    fit_pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    assert lrp.fit_pool is None  # torn down


@pytest.mark.django_db
def test_stalled_heartbeat_own_pid_tears_down():
    """Own pid but last_status_check > 300s ago → the client stopped polling
    and the fit is abandoned; tear the pool down."""
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(
        process_id=os.getpid(),
        last_status_check=time.time() - 400,  # > 300s stale
        start_time=time.time() - 400,
    )
    lrp, fit_pool = _make_lrp(row.pk)

    _run_check(lrp)

    fit_pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    assert lrp.fit_pool is None  # torn down


@pytest.mark.django_db
def test_missing_row_early_returns_without_teardown():
    """status_row_pk points at a deleted/nonexistent row → get_status returns
    None → early return, NO teardown (the superseded fit finishes on its own;
    update_status against the deleted pk is a harmless no-op)."""
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(process_id=os.getpid(), start_time=time.time())
    pk = row.pk
    row.delete()

    lrp, fit_pool = _make_lrp(pk)

    _run_check(lrp)

    fit_pool.shutdown.assert_not_called()
    assert lrp.fit_pool is fit_pool  # not torn down
