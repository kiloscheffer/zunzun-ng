"""Tests for the defensive early-return guard and per-dispatch write isolation.

With per-dispatch isolation each child has its own LRPStatus row AND its own
LRPDispatchData row.  No dispatch deletes a prior row, and there is no shared
session blob that a concurrent child could clobber.

The ``if self.get_status("process_id") is None: return`` guard in
RenderOutputHTMLToAFileAndSetStatusRedirect is now a minor defensive skip: if
the housekeeping age-sweep deletes the row mid-flight the child returns early
rather than trying to write a terminal redirect to a deleted row.  It is NOT a
clobber guard anymore.

Tests in this file cover:
1. Row-gone path: early return with no writes (the guard's surviving purpose).
2. Row-present path: writes + redirect happen normally (guard does not
   over-block).
3. Per-dispatch isolation: a child writing to its own LRPDispatchData row does
   NOT touch a sibling dispatch's row.
"""

import os
from unittest import mock

import pytest


@pytest.mark.django_db
def test_functionfinder_skips_writes_when_row_gone():
    """Guard surviving purpose: if the housekeeping sweep deleted this
    dispatch's LRPStatus row mid-flight, RenderOutputHTMLToAFileAndSetStatusRedirect
    returns early without writing or raising.  No shared blob to clobber — the
    early return just avoids a pointless update_status no-op on a deleted row."""
    from zunzun.LongRunningProcess.FunctionFinder import FunctionFinder

    lrp = FunctionFinder()
    lrp.status_row_pk = 9_999_999  # no such row -> get_status returns None
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
def test_functionfinder_writes_when_row_present():
    """Guard must not over-block: with a live status row the normal
    per-dispatch writes + redirect still happen."""
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
def test_base_render_output_skips_writes_when_row_gone():
    """Guard surviving purpose for the base class: if the housekeeping sweep
    deleted this dispatch's LRPStatus row mid-flight, the method returns early
    without calling SaveSpecificDataToSessionStore or update_status."""
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
    )

    lrp = StatusMonitoredLongRunningProcessPage()
    lrp.status_row_pk = 9_999_999  # no such row -> get_status returns None

    with (
        mock.patch.object(lrp, "SaveSpecificDataToSessionStore") as mock_save,
        mock.patch.object(lrp, "update_status") as mock_update,
    ):
        lrp.RenderOutputHTMLToAFileAndSetStatusRedirect()

    mock_save.assert_not_called()
    mock_update.assert_not_called()


@pytest.mark.django_db
def test_per_dispatch_write_isolation():
    """Per-dispatch isolation: a child writing to its own LRPDispatchData row
    does NOT affect a sibling dispatch's row.  No shared blob exists that one
    child could clobber for another.

    This is the new invariant that replaced the old clobber-guard rationale.
    """
    from zunzun import dispatch_data
    from zunzun.models import LRPDispatchData, LRPStatus

    row_a = LRPStatus.objects.create(start_time=1.0)
    row_b = LRPStatus.objects.create(start_time=2.0)
    LRPDispatchData.objects.create(status=row_a)
    LRPDispatchData.objects.create(status=row_b)

    # Child A writes its data blob.
    dispatch_data.save_items(row_a.pk, "data", {"equation": "y=a*x"})

    # Child B's data blob must be unaffected.
    result = dispatch_data.load_item(row_b.pk, "data", "equation", default=None)
    assert result is None, f"Row B's data blob was contaminated by row A's write: {result!r}"

    # Sanity: row A's own write is visible.
    assert dispatch_data.load_item(row_a.pk, "data", "equation") == "y=a*x"
