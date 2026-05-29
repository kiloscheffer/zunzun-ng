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


@pytest.mark.django_db
def test_update_status_writes_only_its_own_row():
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
    )
    from zunzun.models import LRPStatus

    mine = LRPStatus.objects.create(start_time=1.0)
    other = LRPStatus.objects.create(start_time=2.0, current_status="other")

    lrp = StatusMonitoredLongRunningProcessPage()
    lrp.status_row_pk = mine.pk
    lrp.update_status(current_status="Fitting Data", parallel_count=4)

    assert LRPStatus.objects.get(pk=mine.pk).current_status == "Fitting Data"
    assert LRPStatus.objects.get(pk=mine.pk).parallel_count == 4
    assert LRPStatus.objects.get(pk=other.pk).current_status == "other"


@pytest.mark.django_db
def test_get_status_returns_field_or_default_only_when_row_missing():
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
    )
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(start_time=1.0, process_id=0, redirect_to_results="")
    lrp = StatusMonitoredLongRunningProcessPage()
    lrp.status_row_pk = row.pk
    assert lrp.get_status("process_id", default=-1) == 0
    assert lrp.get_status("redirect_to_results", default="x") == ""

    lrp.status_row_pk = 99999
    assert lrp.get_status("process_id", default=-1) == -1


@pytest.mark.django_db
def test_housekeeping_deletes_aged_status_rows(monkeypatch, tmp_path):
    import time as _time

    from zunzun import views
    from zunzun.models import LRPStatus

    now = _time.time()
    fresh = LRPStatus.objects.create(start_time=now, last_status_check=now)
    stale = LRPStatus.objects.create(
        start_time=now - 10_000_000, last_status_check=now - 10_000_000
    )

    # temp dir arg is unused for this assertion; point it at tmp_path
    views._housekeeping_child(str(tmp_path), 500)

    assert LRPStatus.objects.filter(pk=fresh.pk).exists()
    assert not LRPStatus.objects.filter(pk=stale.pk).exists()
