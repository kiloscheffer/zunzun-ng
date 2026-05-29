"""Tests for the spawn-safe ChildPayload dataclass."""

import pickle
from unittest import mock


def test_child_payload_round_trips():
    from zunzun.LongRunningProcess.child_payload import ChildPayload

    p = ChildPayload(
        lrp_class_path="zunzun.LongRunningProcess.FitOneEquation.FitOneEquation",
        session_key_status="s1",
        session_key_data="s2",
        session_key_functionfinder="s3",
        dimensionality=2,
        renice_level=10,
        data_object=None,
        equation=None,
        extra={"foo": "bar"},
    )
    clone = pickle.loads(pickle.dumps(p, pickle.HIGHEST_PROTOCOL))
    assert clone.lrp_class_path == p.lrp_class_path
    assert clone.dimensionality == 2
    assert clone.extra == {"foo": "bar"}


def test_child_payload_has_required_fields():
    """Ensure the dataclass exposes every field needed by PerformAllWork."""
    import dataclasses

    from zunzun.LongRunningProcess.child_payload import ChildPayload

    fields = {f.name for f in dataclasses.fields(ChildPayload)}
    assert fields == {
        "lrp_class_path",
        "session_key_status",
        "session_key_data",
        "session_key_functionfinder",
        "dimensionality",
        "renice_level",
        "data_object",
        "equation",
        "dispatch_id",
        "extra",
    }


_TEST_DISPATCH_ID = 12345.6789


def _build_fake_lrp_module(
    perform_side_effect=None,
    apply_side_effect=None,
    session_dispatched_at: object = _TEST_DISPATCH_ID,
):
    """Helper: construct a fake module exposing a FakeLRP class whose
    apply_child_payload and PerformAllWork can be wired to raise.

    The FakeLRP also implements LoadItemFromSessionStore returning a
    configurable session_dispatched_at value, so the test can exercise
    the dispatch_id ownership branch of _run_fit_child. By default the
    session value matches the payload's dispatch_id (we own the slot).
    Records every SaveDictionaryOfItemsToSessionStore call in `saves`.
    """
    saves = []

    class FakeLRP:
        def PerformAllWork(self):
            if perform_side_effect is not None:
                raise perform_side_effect

        def apply_child_payload(self, _payload):
            if apply_side_effect is not None:
                raise apply_side_effect

        def SaveDictionaryOfItemsToSessionStore(self, store, payload):
            saves.append((store, payload))

        def LoadItemFromSessionStore(self, _store, key):
            # Default: simulate "we own the slot" — session.dispatched_at
            # matches what the parent stamped on our payload.
            if key == "dispatched_at":
                return session_dispatched_at
            if key == "redirectToResultsFileOrURL":
                return ""
            return None

    fake_module = mock.Mock()
    fake_module.FakeLRP = FakeLRP
    return fake_module, saves


def _run_fit_child_with_fake_lrp(tmp_path, monkeypatch, fake_module, dispatch_id=_TEST_DISPATCH_ID):
    import settings
    from zunzun.LongRunningProcess import child_payload as cp

    monkeypatch.setattr(settings, "TEMP_FILES_DIR", str(tmp_path))
    monkeypatch.setattr(cp.importlib, "import_module", lambda _path: fake_module)
    monkeypatch.setattr(cp, "time", mock.Mock())  # skip the post-work sleep

    payload = cp.ChildPayload(
        lrp_class_path="fake.module.FakeLRP",
        session_key_status="s1",
        session_key_data="s2",
        session_key_functionfinder="s3",
        dimensionality=2,
        renice_level=10,
        data_object=None,
        equation=None,
        dispatch_id=dispatch_id,
    )
    cp._run_fit_child(payload)


def test_run_fit_child_writes_terminal_redirect_on_perform_all_work_exception(
    tmp_path, monkeypatch
):
    """An uncaught exception inside PerformAllWork must produce a terminal
    artifact AND set redirectToResultsFileOrURL so the polling UI completes.
    Exercises the dispatch_id ownership path (payload.dispatch_id matches
    session.dispatched_at → we_own_slot=True → publish redirect).
    """
    import os

    fake_module, saves = _build_fake_lrp_module(
        perform_side_effect=RuntimeError("simulated child failure")
    )
    _run_fit_child_with_fake_lrp(tmp_path, monkeypatch, fake_module)

    redirect_writes = [p for s, p in saves if s == "status" and "redirectToResultsFileOrURL" in p]
    assert len(redirect_writes) == 1
    redirect_path = redirect_writes[0]["redirectToResultsFileOrURL"]
    assert os.path.exists(redirect_path)
    assert "currentStatus" in redirect_writes[0]
    # Bundled write also clears the gate atomically.
    assert redirect_writes[0]["processID"] == 0
    assert redirect_writes[0]["dispatched_at"] == 0


def test_run_fit_child_writes_terminal_redirect_on_apply_child_payload_exception(
    tmp_path, monkeypatch
):
    """Hydration failures (apply_child_payload raises) must also produce a
    terminal redirect — same bug class as PerformAllWork exceptions. Without
    coverage of this path, a subclass forgetting to populate payload.extra
    leaves the polling UI stuck forever.
    """
    import os

    fake_module, saves = _build_fake_lrp_module(
        apply_side_effect=KeyError("payload.extra['missing_field']")
    )
    _run_fit_child_with_fake_lrp(tmp_path, monkeypatch, fake_module)

    redirect_writes = [p for s, p in saves if s == "status" and "redirectToResultsFileOrURL" in p]
    assert len(redirect_writes) == 1
    assert os.path.exists(redirect_writes[0]["redirectToResultsFileOrURL"])
    assert "currentStatus" in redirect_writes[0]


def test_run_fit_child_skips_terminal_redirect_when_newer_dispatch_owns_slot(tmp_path, monkeypatch):
    """When session.dispatched_at differs from payload.dispatch_id, a newer
    dispatch has claimed the slot — we must NOT publish our terminal redirect
    into the shared status session, otherwise the newer fit's polling would
    complete with our error page.
    """
    # session has a NEWER dispatch_id (different from payload's)
    fake_module, saves = _build_fake_lrp_module(
        perform_side_effect=RuntimeError("older fit failed mid-run"),
        session_dispatched_at=99999.0,  # not our dispatch
    )
    _run_fit_child_with_fake_lrp(tmp_path, monkeypatch, fake_module)

    # No SaveDictionaryOfItemsToSessionStore call should publish a redirect
    # for the older (us) fit into the now-newer-owned status session.
    status_writes = [p for s, p in saves if s == "status"]
    assert status_writes == [], (
        f"Expected no status writes when newer dispatch owns slot, got {status_writes}"
    )


def test_run_fit_child_publishes_when_session_dispatched_at_is_missing(tmp_path, monkeypatch):
    """If session.dispatched_at returns None (e.g., key missing because
    session was recreated mid-fit), we should still publish — treating
    None/0 as "no dispatch claimed" matches the legacy pid-fallback
    semantics.
    """
    import os

    fake_module, saves = _build_fake_lrp_module(
        perform_side_effect=RuntimeError("child failed"),
        session_dispatched_at=None,  # session missing the key
    )
    _run_fit_child_with_fake_lrp(tmp_path, monkeypatch, fake_module)

    redirect_writes = [p for s, p in saves if s == "status" and "redirectToResultsFileOrURL" in p]
    assert len(redirect_writes) == 1, (
        "Terminal redirect should still publish when session.dispatched_at is missing"
    )
    assert os.path.exists(redirect_writes[0]["redirectToResultsFileOrURL"])


import pytest  # noqa: E402


@pytest.mark.django_db
def test_run_fit_child_publishes_terminal_redirect_to_a_real_session(tmp_path, monkeypatch):
    """End-to-end failure path against a REAL SQLite session.

    The other _run_fit_child tests above use a FakeLRP whose
    SaveDictionaryOfItemsToSessionStore just appends to a list — they
    prove the handler's logic but mock away the session layer. This one
    swaps in a FailingLRP that *subclasses* StatusMonitoredLongRunningProcessPage,
    so the handler's Load/Save go through the genuine SessionStore +
    NumpySessionSerializer + SQLite-retry machinery. After the child
    fails, we reload the status session from its key and assert the
    terminal redirect actually persisted — the real round-trip the
    polling UI depends on.

    Why not a true os-level spawn: a spawned child is a fresh interpreter
    that (a) can't see a parent-process monkeypatch and (b) can't share
    pytest-django's transaction-scoped test session DB. Driving the real
    _run_fit_child entrypoint in-process with a real session is the
    faithful, deterministic substitute; cross-process pickling is covered
    separately by test_pickle_spike.py and the ChildPayload round-trip
    tests above.
    """
    import os

    from django.contrib.sessions.backends.db import SessionStore

    import settings
    from zunzun.LongRunningProcess import child_payload as cp
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
    )

    dispatch_id = 555.5

    class FailingLRP(StatusMonitoredLongRunningProcessPage):
        # Inherits the REAL LoadItemFromSessionStore /
        # SaveDictionaryOfItemsToSessionStore (hit the real session via
        # session_key_status). Only the work entrypoints are stubbed:
        # apply_child_payload is a no-op (we don't need real hydration to
        # reach the failure), PerformAllWork raises to simulate the fit
        # blowing up after dispatch.
        def apply_child_payload(self, payload):  # noqa: ARG002 — stubbed, hydration not needed
            pass

        def PerformAllWork(self):
            raise RuntimeError("simulated fit failure in child")

    fake_module = mock.Mock()
    fake_module.FailingLRP = FailingLRP

    # Real status session, stamped as owned by THIS dispatch so the
    # handler's ownership check (session.dispatched_at == payload.dispatch_id)
    # resolves to "we own it" and publishes.
    status = SessionStore()
    status.create()
    status["processID"] = os.getpid()
    status["dispatched_at"] = dispatch_id
    status["currentStatus"] = "Fitting Data"
    status.save()
    status_key = status.session_key

    # The child sets session_key_data / _functionfinder on the instance
    # but FailingLRP never writes them; real empty sessions keep the
    # payload shape honest.
    data = SessionStore()
    data.create()
    ff = SessionStore()
    ff.create()

    monkeypatch.setattr(settings, "TEMP_FILES_DIR", str(tmp_path))
    monkeypatch.setattr(cp.importlib, "import_module", lambda _path: fake_module)
    monkeypatch.setattr(cp, "time", mock.Mock())  # skip the 1s post-work sleep

    payload = cp.ChildPayload(
        lrp_class_path="fake.module.FailingLRP",
        session_key_status=status_key,
        session_key_data=data.session_key,
        session_key_functionfinder=ff.session_key,
        dimensionality=2,
        renice_level=10,
        data_object=None,
        equation=None,
        dispatch_id=dispatch_id,
    )

    cp._run_fit_child(payload)

    # Reload the status session straight from the DB (fresh SessionStore,
    # not the in-memory instance we saved earlier) to prove the redirect
    # genuinely persisted through the serialize → SQLite → deserialize path.
    reloaded = SessionStore(status_key)
    redirect = reloaded.get("redirectToResultsFileOrURL")
    assert redirect, "terminal redirect was not published to the real session"
    assert os.path.exists(redirect), f"redirect points to a missing file: {redirect!r}"
    # Bundled, ownership-gated write also clears the per-user gate atomically.
    assert reloaded.get("processID") == 0
    assert reloaded.get("dispatched_at") == 0
    assert reloaded.get("currentStatus")
