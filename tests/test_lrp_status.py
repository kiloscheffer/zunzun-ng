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
    assert row.completed is False

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
def test_current_status_is_unbounded_textfield():
    """current_status must be an unbounded TextField, not CharField(255).

    FunctionFinder's progress path (WorkItems_CheckOneSecondSessionUpdates)
    builds an HTML <table> with one row per included equation family and writes
    it via update_status(current_status=...). A normal multi-family run exceeds
    255 chars; on a length-enforcing backend a CharField(255) would make that
    write fail and abort an otherwise healthy fit. The old session blob had no
    such cap; redirect_to_results is already TextField — match it.
    """
    from django.db import models

    from zunzun.models import LRPStatus

    field = LRPStatus._meta.get_field("current_status")
    assert isinstance(field, models.TextField)
    # TextField reports max_length=None; CharField would report 255 here.
    assert getattr(field, "max_length", None) is None


@pytest.mark.django_db
def test_update_status_accepts_long_html_table():
    """Behavioral companion to the field-type guard: a >255-char HTML status
    (the FunctionFinder family-progress table) round-trips intact."""
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
    )
    from zunzun.models import LRPStatus

    long_status = (
        "<table>"
        + ("<tr><td>1</td><td>of</td><td>9</td><td>Polynomial</td></tr>" * 40)
        + "</table>"
    )
    assert len(long_status) > 255

    row = LRPStatus.objects.create(start_time=1.0)
    lrp = StatusMonitoredLongRunningProcessPage()
    lrp.status_row_pk = row.pk
    lrp.update_status(current_status=long_status)

    assert LRPStatus.objects.get(pk=row.pk).current_status == long_status


@pytest.mark.django_db
def test_housekeeping_deletes_aged_status_rows(tmp_path):
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


@pytest.mark.django_db
def test_housekeeping_initializes_django_before_model_access(monkeypatch, tmp_path):
    """Regression (Codex PR #21, comment 3329374716): _housekeeping_child runs
    in a multiprocessing spawn child — a fresh interpreter with no Django
    bootstrap. It must call django.setup() before touching SessionStore /
    LRPStatus, or the first ORM call raises AppRegistryNotReady, the broad
    except swallows it, and session-clear + the row sweep + the temp-dir prune
    are all silently skipped in production spawn mode.

    pytest pre-initializes Django, so a not-ready registry can't be reproduced
    in-process; instead assert django.setup() is actually invoked (re-running it
    is a safe near-no-op when already configured, matching _run_fit_child).
    """
    import django

    from zunzun import views

    calls = []
    real_setup = django.setup

    def _tracking_setup(*args, **kwargs):
        calls.append(True)
        return real_setup(*args, **kwargs)

    monkeypatch.setattr("django.setup", _tracking_setup)

    views._housekeeping_child(str(tmp_path), 500)

    assert calls, "_housekeeping_child must call django.setup() before model/session access"


@pytest.mark.django_db
def test_mark_running_sets_state_and_pid():
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create()
    assert row.state == LRPStatus.State.INITIALIZING

    LRPStatus.mark_running(row.pk, 4242)

    row.refresh_from_db()
    assert row.state == LRPStatus.State.RUNNING
    assert row.process_id == 4242


@pytest.mark.django_db
def test_mark_terminal_sets_terminal_and_clears_pid():
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create()
    LRPStatus.mark_running(row.pk, 4242)

    LRPStatus.mark_terminal(row.pk)

    row.refresh_from_db()
    assert row.state == LRPStatus.State.TERMINAL
    assert row.process_id == 0


@pytest.mark.django_db
def test_mark_terminal_writes_optional_fields_when_passed():
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create()

    LRPStatus.mark_terminal(
        row.pk,
        redirect="/temp/result.html",
        current_status="done",
        parallel_count=0,
    )

    row.refresh_from_db()
    assert row.redirect_to_results == "/temp/result.html"
    assert row.current_status == "done"
    assert row.parallel_count == 0


@pytest.mark.django_db
def test_mark_terminal_omitted_redirect_does_not_clobber():
    """A bare mark_terminal(pk) must not overwrite a redirect a prior
    successful stage published — the _run_fit_child already-terminal guard
    relies on this."""
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(redirect_to_results="/temp/already.html")

    LRPStatus.mark_terminal(row.pk)  # no redirect kwarg

    row.refresh_from_db()
    assert row.redirect_to_results == "/temp/already.html"
    assert row.state == LRPStatus.State.TERMINAL


@pytest.mark.django_db
def test_mark_terminal_noop_on_missing_row():
    """A superseding dispatch may have deleted the row; the keyed update
    matches zero rows and must not raise."""
    from zunzun.models import LRPStatus

    LRPStatus.mark_terminal(999999)  # nonexistent pk — harmless no-op
