"""Tests for PerformAllWork's pipeline-abort handling.

When the reports phase raises _ReportsPipelineAborted (e.g., due to a
BrokenProcessPool from FitPool), PerformAllWork must NOT continue to
CreateReportPDF or RenderOutputHTMLToAFileAndSetStatusRedirect — those
would overwrite the specific error status with their own messages and
produce a broken redirect to an empty results page.
"""

from unittest import mock

import pytest


def test_perform_all_work_aborts_pipeline_on_reports_failure():
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
        _ReportsPipelineAborted,
    )

    lrp = StatusMonitoredLongRunningProcessPage()

    # Stub out methods that PerformAllWork calls. update_status is mocked so
    # the test doesn't need a real LRPStatus row / DB.
    with (
        mock.patch.object(lrp, "update_status"),
        mock.patch.object(lrp, "GenerateListOfWorkItems"),
        mock.patch.object(lrp, "PerformWorkInParallel"),
        mock.patch.object(lrp, "GenerateListOfOutputReports"),
        mock.patch.object(
            lrp,
            "CreateOutputReportsInParallelUsingProcessPool",
            side_effect=_ReportsPipelineAborted(),
        ),
        mock.patch.object(lrp, "CreateReportPDF") as mock_pdf,
        mock.patch.object(lrp, "RenderOutputHTMLToAFileAndSetStatusRedirect") as mock_html,
    ):
        # Should not raise — sentinel is caught by PerformAllWork
        lrp.PerformAllWork()

    # Critically: PDF and HTML rendering should NOT have been called
    mock_pdf.assert_not_called()
    mock_html.assert_not_called()

    # And the pool should have been torn down (PerformAllWork's finally)
    assert lrp.fit_pool is None


@pytest.mark.django_db
def test_generate_list_of_work_items_aborts_pipeline_on_solve_failure(tmp_path, monkeypatch):
    """Solve() failure must raise _ReportsPipelineAborted so PerformAllWork
    does not continue into report/PDF/HTML stages that would overwrite the
    error redirect with a path to a (broken) success-results page. Also
    verifies the terminal write lands on this dispatch's LRPStatus row:
    redirect_to_results set, process_id cleared.
    """
    from zunzun.LongRunningProcess.FittingBaseClass import FittingBaseClass
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        _ReportsPipelineAborted,
    )
    from zunzun.models import LRPStatus

    # Redirect the error-HTML write to a temp dir so the test doesn't
    # pollute temp/ on real disk.
    monkeypatch.setattr(
        "zunzun.LongRunningProcess.FittingBaseClass.page_artifact_path",
        lambda *_args, **_kwargs: str(tmp_path / "error.html"),
    )

    row = LRPStatus.objects.create(start_time=1.0, process_id=4321, current_status="Fitting Data")

    lrp = FittingBaseClass()
    lrp.status_row_pk = row.pk
    lrp.dataObject = mock.Mock()
    lrp.dataObject.uniqueString = "test"
    lrp.dataObject.equation.Solve.side_effect = RuntimeError("Solve diverged")

    try:
        lrp.GenerateListOfWorkItems()
    except _ReportsPipelineAborted:
        pass
    else:
        raise AssertionError("Expected _ReportsPipelineAborted")

    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert reloaded.redirect_to_results.endswith("error.html")
    # The terminal write also clears the per-user gate.
    assert reloaded.process_id == 0


# ---------------------------------------------------------------------------
# Terminal-error helper coverage.
#
# _write_terminal_error_html() survives the LRPStatus cutover (it writes the
# error HTML *file* and returns the path); only its callers changed (they now
# publish via update_status instead of the retired _publish_terminal_error).
# The pr-test-analyzer review on PR #11 flagged these branches as
# transitively-exercised-but-never-asserted, i.e. the exact lines a future
# refactor could "clean up" with zero test signal.
# ---------------------------------------------------------------------------


def _base_lrp():
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
    )

    return StatusMonitoredLongRunningProcessPage()


def test_write_terminal_error_html_success(monkeypatch, tmp_path):
    """Happy path: returns the artifact path and the file exists on disk."""
    target = tmp_path / "err.html"
    monkeypatch.setattr(
        "zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage.page_artifact_path",
        lambda *_a, **_k: str(target),
    )

    lrp = _base_lrp()
    lrp.dataObject = mock.Mock()
    lrp.dataObject.uniqueString = "abc"

    path = lrp._write_terminal_error_html("something broke")
    assert path == str(target)
    assert target.exists()
    assert target.read_text(encoding="utf-8").strip() != ""


def test_write_terminal_error_html_returns_none_on_disk_failure(monkeypatch, tmp_path):
    """Disk-unwritable: both the template render AND the static fallback
    target the same (unwritable) path, so the helper returns None rather
    than raising — the contract the BrokenProcessPool sites rely on via
    `... or ""`.
    """
    # Path inside a directory that doesn't exist → open() raises for both
    # the template-render write and the hardcoded-fallback write.
    bad = tmp_path / "no_such_dir" / "err.html"
    monkeypatch.setattr(
        "zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage.page_artifact_path",
        lambda *_a, **_k: str(bad),
    )

    lrp = _base_lrp()
    lrp.dataObject = mock.Mock()
    lrp.dataObject.uniqueString = "abc"

    assert lrp._write_terminal_error_html("something broke") is None


@pytest.mark.django_db
def test_broken_process_pool_publishes_terminal_redirect(monkeypatch, tmp_path):
    """A BrokenProcessPool in the reports phase must (a) raise
    _ReportsPipelineAborted so PerformAllWork halts, and (b) publish the
    terminal redirect + gate-clear to this dispatch's LRPStatus row.
    Regression guard against the pre-fix shape that dropped the redirect.
    """
    from concurrent.futures.process import BrokenProcessPool

    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        _ReportsPipelineAborted,
    )
    from zunzun.models import LRPStatus

    monkeypatch.setattr(
        "zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage.page_artifact_path",
        lambda *_a, **_k: str(tmp_path / "err.html"),
    )

    row = LRPStatus.objects.create(start_time=1.0, process_id=4321, current_status="Running")

    lrp = _base_lrp()
    lrp.status_row_pk = row.pk
    lrp.dataObject = mock.Mock()
    lrp.dataObject.uniqueString = "abc"
    lrp.characterizerOutputTrueOrReportOutputFalse = False

    # One report so the method doesn't early-return on an empty list.
    report = mock.Mock()
    report.name = "r1"
    lrp.graphReports = [report]
    lrp.textReports = []

    # The pool dies on first submit.
    lrp.fit_pool = mock.Mock()
    lrp.fit_pool.submit_many.side_effect = BrokenProcessPool("a worker died")

    with pytest.raises(_ReportsPipelineAborted):
        lrp.CreateOutputReportsInParallelUsingProcessPool()

    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert reloaded.redirect_to_results.endswith("err.html")
    assert reloaded.process_id == 0
    assert reloaded.current_status  # carries the user-facing error text
    assert reloaded.parallel_count == 0


def test_all_broken_process_pool_sites_use_terminal_helpers():
    """Structural guard: all BrokenProcessPool handlers route through
    update_status() + _write_terminal_error_html(). If a future edit
    open-codes a save at one of these sites, this catches it without
    needing near-duplicate integration tests.

    The _write_terminal_error_html callers are:
    StatusMonitored base (1) + FunctionFinder.PerformWorkInParallel (2) +
    StatisticalDistributions.PerformWorkInParallel (1).
    """
    import inspect

    from zunzun.LongRunningProcess import (
        FunctionFinder,
        StatisticalDistributions,
        StatusMonitoredLongRunningProcessPage,
    )

    sources = [
        inspect.getsource(
            StatusMonitoredLongRunningProcessPage.StatusMonitoredLongRunningProcessPage.CreateOutputReportsInParallelUsingProcessPool
        ),
        inspect.getsource(FunctionFinder.FunctionFinder.PerformWorkInParallel),
        inspect.getsource(StatisticalDistributions.StatisticalDistributions.PerformWorkInParallel),
    ]
    for src in sources:
        assert "update_status" in src
        assert "_write_terminal_error_html" in src
