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
        "extra",
    }


def _build_fake_lrp_module(perform_side_effect=None, apply_side_effect=None):
    """Helper: construct a fake module exposing a FakeLRP class whose
    apply_child_payload and PerformAllWork can be wired to raise.
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

    fake_module = mock.Mock()
    fake_module.FakeLRP = FakeLRP
    return fake_module, saves


def _run_fit_child_with_fake_lrp(tmp_path, monkeypatch, fake_module):
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
    )
    cp._run_fit_child(payload)


def test_run_fit_child_writes_terminal_redirect_on_perform_all_work_exception(
    tmp_path, monkeypatch
):
    """An uncaught exception inside PerformAllWork must produce a terminal
    artifact AND set redirectToResultsFileOrURL so the polling UI completes.
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
