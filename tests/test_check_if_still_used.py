"""Tests for StatusMonitoredLongRunningProcessPage.CheckIfStillUsed.

CheckIfStillUsed is the abandoned-fit watchdog the spawned child runs once
per second (via _oneSecondStatusUpdate). It reads this dispatch's LRPStatus
row and, when the fit is abandoned, tears down the fit pool + terminates
worker children AND raises _ReportsPipelineAborted so the abort propagates up
to PerformAllWork (which catches it) — stopping the LRP child itself, not just
its pools. Abandonment is ANY of:
  - the row is GONE (get_status -> None): a newer dispatch superseded this one
    and deleted it (delete-prior-row in LongRunningProcessView), or the
    housekeeping age-sweep removed it — either way this fit is abandoned, OR
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

from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
    _ReportsPipelineAborted,
)


def _identity(x):
    """Module-level (picklable) worker fn for the FitPool abort test."""
    return x


def test_submit_many_propagates_pipeline_abort_from_progress():
    """submit_many's progress callback runs the 1-Hz status update, which calls
    CheckIfStillUsed -> _ReportsPipelineAborted on an abandoned fit. That abort
    must propagate out of submit_many, NOT be logged-and-swallowed by the
    progress-callback guard — otherwise the parallel reports phase keeps pulling
    results after teardown and the superseded child runs on.
    """
    from zunzun.parallel_pool import FitPool

    pool = FitPool(max_workers=1)
    try:

        def progress(_done, _total):
            raise _ReportsPipelineAborted()

        with pytest.raises(_ReportsPipelineAborted):
            list(pool.submit_many(_identity, [1, 2, 3], progress=progress))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


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

    with pytest.raises(_ReportsPipelineAborted):
        _run_check(lrp)

    fit_pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    assert lrp.fit_pool is None  # torn down


@pytest.mark.django_db
def test_stalled_heartbeat_own_pid_tears_down():
    """Own pid but last_status_check > 300s ago → the client stopped polling
    and the fit is abandoned; tear the pool down AND abort the pipeline."""
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(
        process_id=os.getpid(),
        last_status_check=time.time() - 400,  # > 300s stale
        start_time=time.time() - 400,
    )
    lrp, fit_pool = _make_lrp(row.pk)

    with pytest.raises(_ReportsPipelineAborted):
        _run_check(lrp)

    fit_pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    assert lrp.fit_pool is None  # torn down


@pytest.mark.django_db
def test_missing_row_tears_down():
    """status_row_pk points at a deleted/nonexistent row → get_status returns
    None → a newer dispatch superseded this one (or housekeeping reclaimed the
    row). The fit is abandoned, so the watchdog must tear the pool down AND
    raise _ReportsPipelineAborted to stop the child, rather than letting a
    superseded CPU-heavy fit run to natural completion."""
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(process_id=os.getpid(), start_time=time.time())
    pk = row.pk
    row.delete()

    lrp, fit_pool = _make_lrp(pk)

    with pytest.raises(_ReportsPipelineAborted):
        _run_check(lrp)

    fit_pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    assert lrp.fit_pool is None  # torn down


@pytest.mark.django_db
def test_serial_worker_reraises_pipeline_abort(monkeypatch):
    """FunctionFinder's all-linear serialWorker runs fits in the CURRENT
    process (no pool child to terminate). When CheckIfStillUsed aborts an
    abandoned fit, the abort must propagate OUT of serialWorker — its
    catch-all except must not swallow _ReportsPipelineAborted, or a superseded
    serial fit keeps burning CPU through the rest of the loop and can still
    progress through the rest of PerformAllWork.
    """
    from zunzun.LongRunningProcess import FunctionFinder as ff

    # parallelWorkFunction returns a falsy result[0] so countOfSerialWorkItemsRun
    # stays 0 -> 0 % 50 == 0 -> the liveness check fires on the first item.
    monkeypatch.setattr(ff, "parallelWorkFunction", lambda _item: [None])
    monkeypatch.setattr(ff, "_install_worker_data_cache", lambda _dc: None)

    class _Obj:
        countOfSerialWorkItemsRun = 0

        def WorkItems_CheckOneSecondSessionUpdates(self):
            raise _ReportsPipelineAborted()

    with pytest.raises(_ReportsPipelineAborted):
        ff.serialWorker(_Obj(), [["item"]], [], dataCache=None)
