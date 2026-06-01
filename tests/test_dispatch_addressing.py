"""Tests for per-dispatch addressing: ownership checks, identical-404 oracle,
token-addressed results, and concurrency caps."""

import os
import time as _time

import pytest
from django.test import Client, RequestFactory

from zunzun.models import LRPStatus
from zunzun.views import _load_owned_status_row


def _request_with_session(session_key):
    req = RequestFactory().get("/")
    req.session = type("S", (), {"session_key": session_key})()
    return req


@pytest.mark.django_db
def test_load_owned_row_returns_row_for_matching_session():
    row = LRPStatus.objects.create(start_time=1.0, owner_session_key="sess-A")
    assert _load_owned_status_row(_request_with_session("sess-A"), row.pk).pk == row.pk


@pytest.mark.django_db
def test_load_owned_row_returns_none_for_foreign_session():
    row = LRPStatus.objects.create(start_time=1.0, owner_session_key="sess-A")
    assert _load_owned_status_row(_request_with_session("sess-B"), row.pk) is None


@pytest.mark.django_db
def test_load_owned_row_returns_none_for_missing_pk_indistinguishably():
    # not-found and not-yours must be indistinguishable (None both ways)
    assert _load_owned_status_row(_request_with_session("sess-A"), 999999) is None


@pytest.mark.django_db
def test_status_page_requires_ownership():
    row = LRPStatus.objects.create(start_time=1.0, owner_session_key="other")
    c = Client()
    c.get("/")  # establishes a session with a different key
    resp = c.get(f"/StatusAndResults/{row.pk}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_results_page_served_by_token_without_cookie(tmp_path, settings):
    settings.TEMP_FILES_DIR = str(tmp_path)
    settings.MEDIA_ROOT = str(tmp_path)
    result_file = tmp_path / "result.html"
    result_file.write_text("<html>RESULT-OK</html>", encoding="utf-8")
    row = LRPStatus.objects.create(
        start_time=1.0,
        result_token="share-tok",
        owner_session_key="someone",
        state=LRPStatus.State.TERMINAL,
        redirect_to_results=str(result_file),
    )
    c = Client()  # fresh, no matching cookie
    resp = c.get(f"/Results/{row.result_token}/")
    assert resp.status_code == 200
    assert b"RESULT-OK" in resp.content


@pytest.mark.django_db
def test_evaluate_reads_dispatch_data_by_token():
    from zunzun.dispatch_data import save_items

    row = LRPStatus.objects.create(start_time=1.0, result_token="eval-tok", owner_session_key="x")
    save_items(
        row.pk,
        "data",
        {
            "dimensionality": 2,
            "equationName": "Linear",
            "equationFamilyName": "Polynomial",
        },
    )
    c = Client()  # no cookie needed (capability)
    resp = c.post("/EvaluateAtAPoint/eval-tok/", {"textPointEditor": "1"})
    # The token resolved the dispatch — we did NOT hit the expired/stale path.
    assert resp.status_code == 200
    assert b"This result has expired." not in resp.content


@pytest.mark.django_db
def test_heartbeat_bumps_only_addressed_row():
    live_pid = os.getpid()  # alive → _finalize_row_if_child_dead leaves the row RUNNING
    a = LRPStatus.objects.create(
        start_time=1.0,
        last_status_check=1.0,
        owner_session_key="S",
        state=LRPStatus.State.RUNNING,
        process_id=live_pid,
    )
    b = LRPStatus.objects.create(
        start_time=1.0,
        last_status_check=1.0,
        owner_session_key="S",
        state=LRPStatus.State.RUNNING,
        process_id=live_pid,
    )
    c = Client()
    s = c.session
    s["lrp_status_pk"] = a.pk
    s.save()
    # stamp the client's real session key onto both rows so the ownership check passes
    LRPStatus.objects.filter(pk__in=[a.pk, b.pk]).update(owner_session_key=s.session_key)
    c.get(f"/StatusUpdate/{a.pk}/")
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.last_status_check > 1.0  # A's row was heartbeated
    assert b.last_status_check == 1.0  # B's row untouched


@pytest.mark.django_db
def test_session_cap_counts_active_rows(settings):
    settings.MAX_CONCURRENT_FITS_PER_SESSION = 1
    settings.MAX_CONCURRENT_FITS_PER_IP = 99
    now = _time.time()
    LRPStatus.objects.create(
        start_time=now,
        last_status_check=now,
        owner_session_key="S",
        owner_ip="1.2.3.4",
        state=LRPStatus.State.RUNNING,
        process_id=999999999,
    )
    from zunzun.views import _active_fit_counts

    per_session, per_ip = _active_fit_counts("S", "1.2.3.4")
    assert per_session == 1
    assert per_ip == 1


@pytest.mark.django_db
def test_stale_heartbeat_not_counted(settings):
    old = _time.time() - 400  # past the 300s window
    LRPStatus.objects.create(
        start_time=old,
        last_status_check=old,
        owner_session_key="S",
        owner_ip="1.2.3.4",
        state=LRPStatus.State.RUNNING,
        process_id=1,
    )
    from zunzun.views import _active_fit_counts

    per_session, per_ip = _active_fit_counts("S", "1.2.3.4")
    assert per_session == 0
