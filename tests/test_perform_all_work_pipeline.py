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
    with mock.patch.object(lrp, "SaveDictionaryOfItemsToSessionStore"), \
         mock.patch.object(lrp, "GenerateListOfWorkItems"), \
         mock.patch.object(lrp, "PerformWorkInParallel"), \
         mock.patch.object(lrp, "GenerateListOfOutputReports"), \
         mock.patch.object(
             lrp, "CreateOutputReportsInParallelUsingProcessPool",
             side_effect=_ReportsPipelineAborted(),
         ), \
         mock.patch.object(lrp, "CreateReportPDF") as mock_pdf, \
         mock.patch.object(lrp, "RenderOutputHTMLToAFileAndSetStatusRedirect") as mock_html:
        # Should not raise — sentinel is caught by PerformAllWork
        lrp.PerformAllWork()

    # Critically: PDF and HTML rendering should NOT have been called
    mock_pdf.assert_not_called()
    mock_html.assert_not_called()

    # And the pool should have been torn down (PerformAllWork's finally)
    assert lrp.fit_pool is None
