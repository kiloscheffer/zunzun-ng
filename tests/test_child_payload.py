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


def test_run_fit_child_writes_terminal_redirect_on_exception(tmp_path, monkeypatch):
    """An uncaught exception inside PerformAllWork must produce a terminal
    artifact AND set redirectToResultsFileOrURL so the polling UI completes.
    Without this, StatusUpdateView returns completed=False forever and the
    user is stuck on the status page until the session expires.
    """
    from zunzun.LongRunningProcess import child_payload as cp

    # Point TEMP_FILES_DIR at the test's tmp_path so the error HTML and
    # log file don't pollute real temp/.
    import settings

    monkeypatch.setattr(settings, "TEMP_FILES_DIR", str(tmp_path))

    saves = []

    class FakeLRP:
        def PerformAllWork(self):
            raise RuntimeError("simulated child failure")

        def apply_child_payload(self, _payload):
            pass

        def SaveDictionaryOfItemsToSessionStore(self, store, payload):
            saves.append((store, payload))

    fake_module = mock.Mock()
    fake_module.FakeLRP = FakeLRP

    monkeypatch.setattr(cp.importlib, "import_module", lambda _path: fake_module)
    monkeypatch.setattr(cp, "time", mock.Mock())  # skip the 1-second post-work sleep

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

    # The exception handler must write both currentStatus AND redirect.
    redirect_writes = [p for s, p in saves if s == "status" and "redirectToResultsFileOrURL" in p]
    assert len(redirect_writes) == 1
    redirect_path = redirect_writes[0]["redirectToResultsFileOrURL"]
    # File should have been written so StatusView can serve it.
    import os

    assert os.path.exists(redirect_path)
    # The same write also carries the user-visible status text.
    assert "currentStatus" in redirect_writes[0]
