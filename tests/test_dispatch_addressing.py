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


@pytest.mark.django_db
def test_retention_sweep_reaps_only_file_backed_rows_whose_file_is_gone(tmp_path, settings):
    settings.TEMP_FILES_DIR = str(tmp_path)
    from zunzun.views import _sweep_orphaned_terminal_rows

    # (1) file-backed, file MISSING -> reaped
    gone = LRPStatus.objects.create(
        start_time=1.0,
        state=LRPStatus.State.TERMINAL,
        redirect_to_results=str(tmp_path / "missing.html"),
    )
    # (1) file-backed, file PRESENT -> kept
    present_file = tmp_path / "present.html"
    present_file.write_text("x", encoding="utf-8")
    kept = LRPStatus.objects.create(
        start_time=1.0, state=LRPStatus.State.TERMINAL, redirect_to_results=str(present_file)
    )
    # (2) URL-redirect (FunctionFinder) -> NOT reaped (not a file path)
    url_row = LRPStatus.objects.create(
        start_time=1.0,
        state=LRPStatus.State.TERMINAL,
        redirect_to_results="/FunctionFinderResults/2/?RANK=1",
    )
    # non-TERMINAL row -> never touched
    running = LRPStatus.objects.create(
        start_time=1.0,
        state=LRPStatus.State.RUNNING,
        redirect_to_results=str(tmp_path / "missing2.html"),
    )

    _sweep_orphaned_terminal_rows()

    assert not LRPStatus.objects.filter(pk=gone.pk).exists()  # file gone -> reaped
    assert LRPStatus.objects.filter(pk=kept.pk).exists()  # file present -> kept
    assert LRPStatus.objects.filter(pk=url_row.pk).exists()  # URL result -> kept
    assert LRPStatus.objects.filter(pk=running.pk).exists()  # not terminal -> kept


# ──────────────────────────────────────────────────────────────────────────────
# Age-sweep: file-backed TERMINAL results must survive SESSION_COOKIE_AGE
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_age_sweep_keeps_file_backed_results(tmp_path, settings):
    """_sweep_aged_rows() must NOT delete TERMINAL rows whose redirect_to_results
    points to a file under TEMP_FILES_DIR — those are retained by
    _sweep_orphaned_terminal_rows() (tied to the file's existence), so a
    shareable /Results/<token>/ link survives past session expiry.

    Rows that SHOULD be deleted by the age-sweep:
      - TERMINAL rows with a URL-redirect (FunctionFinder, not a file path)
      - In-progress (RUNNING) rows with old timestamps
    """
    from zunzun.views import _sweep_aged_rows

    settings.TEMP_FILES_DIR = str(tmp_path)
    settings.SESSION_COOKIE_AGE = 100  # short window so old rows trigger the sweep

    # Very old timestamps — both well past SESSION_COOKIE_AGE.
    old_time = 1.0

    # (1) TERMINAL, file-backed, file EXISTS under TEMP_FILES_DIR -> KEPT
    result_file = tmp_path / "r.html"
    result_file.write_text("<html>RESULT</html>", encoding="utf-8")
    kept_file_row = LRPStatus.objects.create(
        start_time=old_time,
        last_status_check=old_time,
        state=LRPStatus.State.TERMINAL,
        redirect_to_results=str(result_file),
    )

    # (2) TERMINAL, URL-redirect (FunctionFinder result, not a file) -> DELETED
    url_row = LRPStatus.objects.create(
        start_time=old_time,
        last_status_check=old_time,
        state=LRPStatus.State.TERMINAL,
        redirect_to_results="/FunctionFinderResults/2/?RANK=1",
    )

    # (3) RUNNING (in-progress), old timestamps, empty redirect -> DELETED
    running_row = LRPStatus.objects.create(
        start_time=old_time,
        last_status_check=old_time,
        state=LRPStatus.State.RUNNING,
        redirect_to_results="",
    )

    _sweep_aged_rows()

    assert LRPStatus.objects.filter(pk=kept_file_row.pk).exists(), (
        "File-backed TERMINAL result must NOT be age-reaped — "
        "it should survive session expiry until the temp/ file is pruned."
    )
    assert not LRPStatus.objects.filter(pk=url_row.pk).exists(), (
        "URL-redirect TERMINAL row (FunctionFinder) must be age-reaped."
    )
    assert not LRPStatus.objects.filter(pk=running_row.pk).exists(), (
        "Abandoned RUNNING row must be age-reaped."
    )


# ──────────────────────────────────────────────────────────────────────────────
# B3: ResultsView error branches
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_results_view_bogus_token_returns_expired_message(client):
    """B3a: GET /Results/bogus-token/ -> 200 with 'expired or is not yet ready'."""
    resp = client.get("/Results/bogus-token-that-does-not-exist/")
    assert resp.status_code == 200
    assert b"expired or is not yet ready" in resp.content


@pytest.mark.django_db
def test_results_view_missing_file_returns_expired_message(client, tmp_path, settings):
    """B3b: A TERMINAL row with a known result_token whose redirect_to_results
    points to a NON-EXISTENT file under TEMP_FILES_DIR returns 200 containing
    'This result has expired.' — exercises the FileNotFoundError arm added in A3.
    """
    settings.TEMP_FILES_DIR = str(tmp_path)
    settings.MEDIA_ROOT = str(tmp_path)

    row = LRPStatus.objects.create(
        start_time=1.0,
        state=LRPStatus.State.TERMINAL,
        redirect_to_results=str(tmp_path / "missing_result.html"),
        owner_session_key="someone",
    )

    resp = client.get(f"/Results/{row.result_token}/")
    assert resp.status_code == 200
    assert b"This result has expired." in resp.content


# ──────────────────────────────────────────────────────────────────────────────
# B4: EvaluateAtAPoint expired-token positive assertion
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_evaluate_at_a_point_bogus_token_returns_expired(client):
    """B4: POST /EvaluateAtAPoint/bogus-token/ -> response body contains
    'This result has expired.' — confirms the row-is-None guard in
    EvaluateAtAPointView.
    """
    resp = client.post("/EvaluateAtAPoint/bogus-token-xyz/", {"x": "1.0"})
    assert resp.status_code == 200
    assert b"This result has expired." in resp.content


# ──────────────────────────────────────────────────────────────────────────────
# FunctionFinder retention-anchor helpers (_unique.py)
# ──────────────────────────────────────────────────────────────────────────────


def test_ff_anchor_path_under_temp_dir(settings, tmp_path):
    """ff_anchor_path() is a deterministic, pk-keyed path under TEMP_FILES_DIR
    with the distinct `ffanchor_` prefix (outside the zun_/h artifact grammar)."""
    from zunzun.LongRunningProcess._unique import ff_anchor_path

    settings.TEMP_FILES_DIR = str(tmp_path)
    assert ff_anchor_path(42) == os.path.join(str(tmp_path), "ffanchor_42")


def test_write_ff_anchor_creates_marker(settings, tmp_path):
    from zunzun.LongRunningProcess._unique import ff_anchor_path, write_ff_anchor

    settings.TEMP_FILES_DIR = str(tmp_path)
    path = write_ff_anchor(7)
    assert path == ff_anchor_path(7)
    assert os.path.exists(path)


def test_touch_ff_anchor_refreshes_mtime(settings, tmp_path):
    from zunzun.LongRunningProcess._unique import touch_ff_anchor, write_ff_anchor

    settings.TEMP_FILES_DIR = str(tmp_path)
    path = write_ff_anchor(7)
    old = _time.time() - 10_000
    os.utime(path, (old, old))
    touch_ff_anchor(7)
    assert os.path.getmtime(path) > old


def test_touch_ff_anchor_missing_is_noop(settings, tmp_path):
    """A missing marker (already reaped/pruned) must not raise."""
    from zunzun.LongRunningProcess._unique import touch_ff_anchor

    settings.TEMP_FILES_DIR = str(tmp_path)
    touch_ff_anchor(999)  # no file on disk; must be a silent no-op
