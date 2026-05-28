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
