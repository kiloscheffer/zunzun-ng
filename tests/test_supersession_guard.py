"""Tests for the superseded-dispatch guard on shared-session blob writes.

The `data` and `functionfinder` session stores are still per-USER blobs
(reused across dispatches). When a newer dispatch supersedes an older one it
deletes the older dispatch's LRPStatus row (delete-prior-row in
LongRunningProcessView). A still-running superseded child must therefore NOT
write those shared blobs, or it would clobber the winning dispatch's results
that `/FunctionFinderResults/` and EvaluateAtAPoint later read.

A missing status row (get_status -> None) is the supersession signal; the
RenderOutputHTML methods short-circuit on it before any shared-state write.
"""

import os
from unittest import mock

import pytest


@pytest.mark.django_db
def test_functionfinder_skips_shared_blob_write_when_superseded():
    """A superseded FunctionFinder child (its status row deleted) must NOT
    write the shared functionfinder/data blobs nor set a redirect."""
    from zunzun.LongRunningProcess.FunctionFinder import FunctionFinder

    lrp = FunctionFinder()
    lrp.status_row_pk = 9_999_999  # no such row -> superseded
    lrp.functionFinderResultsList = [["x"]]
    lrp.dataObject = mock.Mock()
    lrp.dataObject.dimensionality = 2

    with (
        mock.patch.object(lrp, "SaveDictionaryOfItemsToSessionStore") as mock_save,
        mock.patch.object(lrp, "update_status") as mock_update,
    ):
        lrp.RenderOutputHTMLToAFileAndSetStatusRedirect()

    mock_save.assert_not_called()
    mock_update.assert_not_called()


@pytest.mark.django_db
def test_functionfinder_writes_shared_blob_when_row_present():
    """Guard must not over-block: with a live status row the normal
    shared-blob writes + redirect still happen."""
    from zunzun.LongRunningProcess.FunctionFinder import FunctionFinder
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(process_id=os.getpid(), start_time=1.0)

    lrp = FunctionFinder()
    lrp.status_row_pk = row.pk
    lrp.functionFinderResultsList = [["x"]]
    lrp.dataObject = mock.Mock()
    lrp.dataObject.dimensionality = 3  # 3D skips the 2D logLin extra write

    with (
        mock.patch.object(lrp, "SaveDictionaryOfItemsToSessionStore") as mock_save,
        mock.patch.object(lrp, "mark_terminal") as mock_terminal,
    ):
        lrp.RenderOutputHTMLToAFileAndSetStatusRedirect()

    assert mock_save.called
    assert mock_terminal.called


@pytest.mark.django_db
def test_base_render_output_skips_shared_writes_when_superseded():
    """The base RenderOutputHTML writes the shared `data` blob via
    SaveSpecificDataToSessionStore (read later by EvaluateAtAPoint). A
    superseded dispatch (row deleted) must skip it."""
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
    )

    lrp = StatusMonitoredLongRunningProcessPage()
    lrp.status_row_pk = 9_999_999  # no such row -> superseded

    with (
        mock.patch.object(lrp, "SaveSpecificDataToSessionStore") as mock_save,
        mock.patch.object(lrp, "update_status") as mock_update,
    ):
        lrp.RenderOutputHTMLToAFileAndSetStatusRedirect()

    mock_save.assert_not_called()
    mock_update.assert_not_called()
