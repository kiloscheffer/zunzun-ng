"""Tests for the LRPStatus per-dispatch status row."""

import pytest


@pytest.mark.django_db
def test_lrpstatus_defaults_and_roundtrip():
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(start_time=111.0, current_status="Initializing")
    assert row.pk is not None
    assert row.current_status == "Initializing"
    assert row.start_time == 111.0
    assert row.last_status_check == 0.0
    assert row.redirect_to_results == ""
    assert row.parallel_count == 0
    assert row.process_id == 0

    LRPStatus.objects.filter(pk=row.pk).update(process_id=4321, current_status="Fitting Data")
    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert reloaded.process_id == 4321
    assert reloaded.current_status == "Fitting Data"
