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


# ---------------------------------------------------------------------------
# Dispatch-ownership and terminal-error helper coverage.
#
# These cover the three helpers landed on StatusMonitoredLongRunningProcessPage
# by fix/pipeline-error-redirects (PR #11) — _we_own_status_slot(),
# _write_terminal_error_html(), _publish_terminal_error() — and the two
# gated call sites (BrokenProcessPool handler, success-path entry gate).
# The pr-test-analyzer review on PR #11 flagged these branches as
# transitively-exercised-but-never-asserted, i.e. the exact lines a future
# refactor could "clean up" with zero test signal.
# ---------------------------------------------------------------------------


def _base_lrp():
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
    )

    return StatusMonitoredLongRunningProcessPage()


def test_we_own_status_slot_true_when_pid_and_dispatch_match(monkeypatch):
    """pid match AND dispatched_at match → we own the slot."""
    import os

    lrp = _base_lrp()
    lrp.dispatched_at = 999.5

    def _load(store, key):
        assert store == "status"
        if key == "processID":
            return os.getpid()
        if key == "dispatched_at":
            return 999.5
        return None

    monkeypatch.setattr(lrp, "LoadItemFromSessionStore", _load)
    assert lrp._we_own_status_slot() is True


def test_we_own_status_slot_false_when_dispatch_mismatch(monkeypatch):
    """pid matches but dispatched_at differs → a newer fit owns the slot.

    This is the dual-identity check's whole reason for existing: the OS
    can recycle a pid, and a newer fit's SetInitialStatusDataIntoSessionVariables
    overwrites session.dispatched_at without touching processID.
    """
    import os

    lrp = _base_lrp()
    lrp.dispatched_at = 999.5

    def _load(store, key):
        if key == "processID":
            return os.getpid()
        if key == "dispatched_at":
            return 111.1  # newer dispatch stamped a different value
        return None

    monkeypatch.setattr(lrp, "LoadItemFromSessionStore", _load)
    assert lrp._we_own_status_slot() is False


def test_we_own_status_slot_true_on_session_read_failure(monkeypatch, caplog):
    """Transient SQLite read failure → default to we-own=True (and log it).

    This is the load-bearing branch documented in the helper's docstring:
    letting a read hiccup return False would suppress the success redirect
    and re-introduce the stuck-poll bug PR #11 fixed. OperationalError is a
    subclass of DatabaseError, so it exercises the except clause.
    """
    import logging

    from django.db import OperationalError

    lrp = _base_lrp()
    lrp.dispatched_at = 999.5

    def _load(store, key):
        raise OperationalError("database is locked")

    monkeypatch.setattr(lrp, "LoadItemFromSessionStore", _load)

    with caplog.at_level(logging.ERROR):
        assert lrp._we_own_status_slot() is True
    assert "Ownership check session read failed" in caplog.text


def test_write_terminal_error_html_success(monkeypatch, tmp_path):
    """Happy path: returns the artifact path and the file exists on disk."""
    from unittest import mock

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
    than raising — the contract the four BrokenProcessPool sites rely on
    via `if html_path:`.
    """
    from unittest import mock

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


def test_broken_process_pool_publishes_bundled_terminal_redirect(monkeypatch, tmp_path):
    """A BrokenProcessPool in the reports phase must (a) raise
    _ReportsPipelineAborted so PerformAllWork halts, and (b) publish a
    single ownership-gated write bundling the terminal redirect with the
    gate-clear (processID:0 / dispatched_at:0). Regression guard against
    the pre-fix two-call shape that dropped the redirect.
    """
    import os
    from concurrent.futures.process import BrokenProcessPool
    from unittest import mock

    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        _ReportsPipelineAborted,
    )

    monkeypatch.setattr(
        "zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage.page_artifact_path",
        lambda *_a, **_k: str(tmp_path / "err.html"),
    )

    lrp = _base_lrp()
    lrp.dispatched_at = 42.0
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

    # We still own the slot, so the terminal write must publish.
    def _load(store, key):
        if key == "processID":
            return os.getpid()
        if key == "dispatched_at":
            return 42.0
        return None

    monkeypatch.setattr(lrp, "LoadItemFromSessionStore", _load)

    saves = []
    monkeypatch.setattr(
        lrp,
        "SaveDictionaryOfItemsToSessionStore",
        lambda store, payload: saves.append((store, payload)),
    )

    import pytest

    with pytest.raises(_ReportsPipelineAborted):
        lrp.CreateOutputReportsInParallelUsingProcessPool()

    redirect_writes = [p for s, p in saves if s == "status" and "redirectToResultsFileOrURL" in p]
    assert len(redirect_writes) == 1
    bundled = redirect_writes[0]
    assert bundled["redirectToResultsFileOrURL"].endswith("err.html")
    assert bundled["processID"] == 0
    assert bundled["dispatched_at"] == 0
    assert bundled["currentStatus"]  # carries the user-facing error text


def test_all_broken_process_pool_sites_use_terminal_helpers():
    """Structural guard: all four BrokenProcessPool handlers route through
    _publish_terminal_error() + _write_terminal_error_html(). If a future
    edit open-codes a save at one of these sites, this catches it without
    needing four near-duplicate integration tests.

    The four sites are the _write_terminal_error_html callers:
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
        assert "_publish_terminal_error" in src
        assert "_write_terminal_error_html" in src


def test_render_output_html_entry_gate_skips_all_writes_when_not_owner(monkeypatch):
    """Success-path entry gate: when a newer dispatch owns the slot,
    RenderOutputHTMLToAFileAndSetStatusRedirect must return before ANY
    shared-session write (the original race was an older child publishing
    its success redirect over a newer fit's slot). smoke runs one fit at a
    time, so only a unit test catches a dropped gate here.
    """
    import os

    lrp = _base_lrp()
    lrp.dispatched_at = 42.0

    def _load(store, key):
        if key == "processID":
            return os.getpid()
        if key == "dispatched_at":
            return 999.9  # newer dispatch owns the slot now
        return None

    monkeypatch.setattr(lrp, "LoadItemFromSessionStore", _load)

    calls = []
    monkeypatch.setattr(
        lrp, "SaveDictionaryOfItemsToSessionStore", lambda *a, **k: calls.append(("status", a))
    )
    monkeypatch.setattr(
        lrp, "SaveSpecificDataToSessionStore", lambda *a, **k: calls.append(("specific", a))
    )

    lrp.RenderOutputHTMLToAFileAndSetStatusRedirect()
    assert calls == []  # entry gate returned before touching the session
