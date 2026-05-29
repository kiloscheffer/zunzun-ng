"""Tests for PerformAllWork's pipeline-abort handling.

When the reports phase raises _ReportsPipelineAborted (e.g., due to a
BrokenProcessPool from FitPool), PerformAllWork must NOT continue to
CreateReportPDF or RenderOutputHTMLToAFileAndSetStatusRedirect — those
would overwrite the specific error status with their own messages and
produce a broken redirect to an empty results page.
"""

from unittest import mock


def test_perform_all_work_aborts_pipeline_on_reports_failure():
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
        _ReportsPipelineAborted,
    )

    lrp = StatusMonitoredLongRunningProcessPage()

    # Stub out methods that PerformAllWork calls
    with (
        mock.patch.object(lrp, "SaveDictionaryOfItemsToSessionStore"),
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


def test_generate_list_of_work_items_aborts_pipeline_on_solve_failure(tmp_path, monkeypatch):
    """Solve() failure must raise _ReportsPipelineAborted so PerformAllWork
    does not continue into report/PDF/HTML stages that would overwrite the
    error redirect with a path to a (broken) success-results page. Also
    verifies the dispatch-ownership-gated session write — when we own
    the slot (pid AND dispatch_id match), the error redirect must be
    published; the gate clear is bundled into the same write.
    """
    import os as _os

    from zunzun.LongRunningProcess.FittingBaseClass import FittingBaseClass
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        _ReportsPipelineAborted,
    )

    # Redirect the error-HTML write to a temp dir so the test doesn't
    # pollute temp/ on real disk.
    monkeypatch.setattr(
        "zunzun.LongRunningProcess.FittingBaseClass.page_artifact_path",
        lambda *_args, **_kwargs: str(tmp_path / "error.html"),
    )

    lrp = FittingBaseClass()
    lrp.dataObject = mock.Mock()
    lrp.dataObject.uniqueString = "test"
    lrp.dataObject.equation.Solve.side_effect = RuntimeError("Solve diverged")
    # Simulate the parent's SetInitialStatusDataIntoSessionVariables
    # having stamped a dispatch_id; the child carries the same value
    # via apply_child_payload (test inlines the assignment).
    lrp.dispatched_at = 12345.6789

    saves = []
    monkeypatch.setattr(
        lrp,
        "SaveDictionaryOfItemsToSessionStore",
        lambda store, payload: saves.append((store, payload)),
    )

    # Simulate "we own the slot": session.processID matches our pid,
    # session.dispatched_at matches our stamped dispatch_id.
    def _load(store, key):
        if key == "processID":
            return _os.getpid()
        if key == "dispatched_at":
            return lrp.dispatched_at
        return 0

    monkeypatch.setattr(lrp, "LoadItemFromSessionStore", _load)

    try:
        lrp.GenerateListOfWorkItems()
    except _ReportsPipelineAborted:
        pass
    else:
        raise AssertionError("Expected _ReportsPipelineAborted")

    # The error redirect must have been written before the raise (under
    # the new structure, redirect + gate clear are bundled into one
    # ownership-gated write).
    redirect_writes = [p for s, p in saves if s == "status" and "redirectToResultsFileOrURL" in p]
    assert len(redirect_writes) == 1
    assert redirect_writes[0]["redirectToResultsFileOrURL"].endswith("error.html")
    # The bundled write also clears the per-user gate.
    assert redirect_writes[0]["processID"] == 0
    assert redirect_writes[0]["dispatched_at"] == 0
