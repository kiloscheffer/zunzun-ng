"""Tests for the spawn-safe ChildPayload dataclass."""

import pickle
from unittest import mock

import pytest


def test_child_payload_round_trips():
    from zunzun.LongRunningProcess.child_payload import ChildPayload

    p = ChildPayload(
        lrp_class_path="zunzun.LongRunningProcess.FitOneEquation.FitOneEquation",
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
        "session_key_data",
        "session_key_functionfinder",
        "dimensionality",
        "renice_level",
        "data_object",
        "equation",
        "status_row_pk",
        "extra",
    }


def _build_fake_lrp_module(perform_side_effect=None, apply_side_effect=None):
    """Helper: construct a fake module exposing a FakeLRP class whose
    apply_child_payload and PerformAllWork can be wired to raise.

    The FakeLRP is a thin stub — the terminal-error handler in
    _run_fit_child addresses the LRPStatus row by payload.status_row_pk
    directly (no session reads, no ownership check), so the fake only
    needs the two work entrypoints. The tests assert against a real
    LRPStatus row.
    """

    class FakeLRP:
        def PerformAllWork(self):
            if perform_side_effect is not None:
                raise perform_side_effect

        def apply_child_payload(self, _payload):
            if apply_side_effect is not None:
                raise apply_side_effect

    fake_module = mock.Mock()
    fake_module.FakeLRP = FakeLRP
    return fake_module


def _run_fit_child_with_fake_lrp(tmp_path, monkeypatch, fake_module, status_row_pk):
    import settings
    from zunzun.LongRunningProcess import child_payload as cp

    monkeypatch.setattr(settings, "TEMP_FILES_DIR", str(tmp_path))
    monkeypatch.setattr(cp.importlib, "import_module", lambda _path: fake_module)
    monkeypatch.setattr(cp, "time", mock.Mock())  # skip the post-work sleep

    payload = cp.ChildPayload(
        lrp_class_path="fake.module.FakeLRP",
        session_key_data="s2",
        session_key_functionfinder="s3",
        dimensionality=2,
        renice_level=10,
        data_object=None,
        equation=None,
        status_row_pk=status_row_pk,
    )
    cp._run_fit_child(payload)


@pytest.mark.django_db
def test_run_fit_child_writes_terminal_redirect_on_perform_all_work_exception(
    tmp_path, monkeypatch
):
    """An uncaught exception inside PerformAllWork must produce a terminal
    artifact AND set redirect_to_results on this dispatch's LRPStatus row
    so the polling UI completes.
    """
    import os

    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(start_time=1.0, current_status="Fitting Data")

    fake_module = _build_fake_lrp_module(
        perform_side_effect=RuntimeError("simulated child failure")
    )
    _run_fit_child_with_fake_lrp(tmp_path, monkeypatch, fake_module, status_row_pk=row.pk)

    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert reloaded.redirect_to_results
    assert os.path.exists(reloaded.redirect_to_results)
    assert reloaded.current_status  # carries the user-facing error text
    # Terminal write also clears the per-user gate.
    assert reloaded.process_id == 0


@pytest.mark.django_db
def test_run_fit_child_writes_terminal_redirect_on_apply_child_payload_exception(
    tmp_path, monkeypatch
):
    """Hydration failures (apply_child_payload raises) must also produce a
    terminal redirect — same bug class as PerformAllWork exceptions. Without
    coverage of this path, a subclass forgetting to populate payload.extra
    leaves the polling UI stuck forever.
    """
    import os

    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(start_time=1.0, current_status="Initializing")

    fake_module = _build_fake_lrp_module(
        apply_side_effect=KeyError("payload.extra['missing_field']")
    )
    _run_fit_child_with_fake_lrp(tmp_path, monkeypatch, fake_module, status_row_pk=row.pk)

    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert reloaded.redirect_to_results
    assert os.path.exists(reloaded.redirect_to_results)
    assert reloaded.current_status
    assert reloaded.process_id == 0


@pytest.mark.django_db
def test_run_fit_child_terminal_write_lands_only_on_its_own_row(tmp_path, monkeypatch):
    """An older child's terminal write must touch ONLY its own row.

    There is no longer a "skip when a newer dispatch owns the slot" branch
    — the write is unconditional but isolated: each dispatch owns its own
    LRPStatus row. Create two rows (old, new), run the failing child against
    the OLD pk, and assert the NEW row (the one StatusView would point at)
    is untouched.
    """
    from zunzun.models import LRPStatus

    old = LRPStatus.objects.create(start_time=1.0, current_status="old fit")
    new = LRPStatus.objects.create(start_time=2.0, current_status="new fit")

    fake_module = _build_fake_lrp_module(
        perform_side_effect=RuntimeError("older fit failed mid-run")
    )
    _run_fit_child_with_fake_lrp(tmp_path, monkeypatch, fake_module, status_row_pk=old.pk)

    # Our (old) row received the terminal redirect...
    assert LRPStatus.objects.get(pk=old.pk).redirect_to_results
    # ...and the newer dispatch's row is completely untouched.
    new_reloaded = LRPStatus.objects.get(pk=new.pk)
    assert new_reloaded.redirect_to_results == ""
    assert new_reloaded.current_status == "new fit"


@pytest.mark.django_db
def test_run_fit_child_terminal_write_against_deleted_row_is_harmless(tmp_path, monkeypatch):
    """If a newer dispatch deleted our row, the terminal update matches zero
    rows and is a harmless no-op (no exception escapes the handler).
    """
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(start_time=1.0)
    deleted_pk = row.pk
    row.delete()

    fake_module = _build_fake_lrp_module(perform_side_effect=RuntimeError("child failed"))
    # Should not raise even though the row no longer exists.
    _run_fit_child_with_fake_lrp(tmp_path, monkeypatch, fake_module, status_row_pk=deleted_pk)

    assert not LRPStatus.objects.filter(pk=deleted_pk).exists()


@pytest.mark.django_db
def test_run_fit_child_does_not_clobber_an_already_completed_row(tmp_path, monkeypatch):
    """A late exception after the fit already finalized must NOT overwrite a
    served-and-cleared success with an error redirect.

    Scenario: RenderOutputHTML succeeded (called mark_terminal + set a redirect),
    StatusView then served the result and CLEARED redirect_to_results to "",
    and only afterwards a post-completion line in the child raised. The
    terminal handler guards on the durable `state == TERMINAL` flag — NOT on
    redirect_to_results (which StatusView blanks on serve) — so it leaves the
    finished row alone. With the old redirect-based guard this test fails (the
    empty redirect reads as "nothing set yet" and the handler clobbers it).
    """
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.create(
        start_time=1.0,
        current_status="done",
        state=LRPStatus.State.TERMINAL,
        redirect_to_results="",
    )

    fake_module = _build_fake_lrp_module(
        perform_side_effect=RuntimeError("post-completion cleanup raised")
    )
    _run_fit_child_with_fake_lrp(tmp_path, monkeypatch, fake_module, status_row_pk=row.pk)

    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert reloaded.redirect_to_results == ""  # not clobbered with an error page
    assert reloaded.current_status == "done"  # not clobbered with the error message
    assert reloaded.state == LRPStatus.State.TERMINAL


@pytest.mark.django_db
def test_run_fit_child_publishes_terminal_redirect_to_a_real_row(tmp_path, monkeypatch):
    """End-to-end failure path against a REAL SQLite-backed LRPStatus row.

    Swaps in a FailingLRP that *subclasses* StatusMonitoredLongRunningProcessPage,
    so the terminal write goes through the genuine ORM + SQLite path. After
    the child fails, we reload the row and assert the terminal redirect
    actually persisted — the real round-trip the polling UI depends on.

    Why not a true os-level spawn: a spawned child is a fresh interpreter
    that (a) can't see a parent-process monkeypatch and (b) can't share
    pytest-django's transaction-scoped test DB. Driving the real
    _run_fit_child entrypoint in-process is the faithful, deterministic
    substitute; cross-process pickling is covered separately by
    test_pickle_spike.py and the ChildPayload round-trip tests above.
    """
    import os

    import settings
    from zunzun.LongRunningProcess import child_payload as cp
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
    )
    from zunzun.models import LRPStatus

    class FailingLRP(StatusMonitoredLongRunningProcessPage):
        # Inherits the REAL update_status (which hits the row via
        # status_row_pk). Only the work entrypoints are stubbed.
        def apply_child_payload(self, payload):  # noqa: ARG002 — stubbed, hydration not needed
            pass

        def PerformAllWork(self):
            raise RuntimeError("simulated fit failure in child")

    fake_module = mock.Mock()
    fake_module.FailingLRP = FailingLRP

    # Real row, owned by this dispatch (pid set as if a fit were running).
    row = LRPStatus.objects.create(
        start_time=1.0, current_status="Fitting Data", process_id=os.getpid()
    )

    monkeypatch.setattr(settings, "TEMP_FILES_DIR", str(tmp_path))
    monkeypatch.setattr(cp.importlib, "import_module", lambda _path: fake_module)
    monkeypatch.setattr(cp, "time", mock.Mock())  # skip the 1s post-work sleep

    payload = cp.ChildPayload(
        lrp_class_path="fake.module.FailingLRP",
        session_key_data="",
        session_key_functionfinder="",
        dimensionality=2,
        renice_level=10,
        data_object=None,
        equation=None,
        status_row_pk=row.pk,
    )

    cp._run_fit_child(payload)

    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert reloaded.redirect_to_results, "terminal redirect was not published to the row"
    assert os.path.exists(reloaded.redirect_to_results), (
        f"redirect points to a missing file: {reloaded.redirect_to_results!r}"
    )
    # Terminal write also clears the per-user gate.
    assert reloaded.process_id == 0
    assert reloaded.current_status


@pytest.mark.django_db
def test_run_fit_child_publishes_redirect_after_real_base_finally(tmp_path, monkeypatch):
    """Regression (Codex PR #21, comment 3328499506): an ordinary Exception in
    the REAL base-class PerformAllWork runs its `finally`, which clears
    process_id to release the per-user gate. The _run_fit_child handler must
    STILL publish the terminal error redirect — i.e. the finally must NOT
    pre-set state=TERMINAL, or the handler's `already terminal` guard skips the
    redirect and orphans the error artifact (the user then lands on the generic
    "no results" page instead of the specific error page).

    Unlike the FakeLRP/FailingLRP stubs above (which replace PerformAllWork
    wholesale, so the genuine try/finally never runs), this subclass overrides
    only an inner work step — exercising the exact finally -> child-handler
    ordering the state=TERMINAL interaction depends on.
    """
    import os

    import settings
    from zunzun.LongRunningProcess import StatusMonitoredLongRunningProcessPage as _mod
    from zunzun.LongRunningProcess import child_payload as cp
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
    )
    from zunzun.models import LRPStatus

    class RealBaseFailingWorkLRP(StatusMonitoredLongRunningProcessPage):
        def apply_child_payload(self, payload):
            self.status_row_pk = payload.status_row_pk

        def GenerateListOfWorkItems(self):
            raise RuntimeError("work boom (real base finally runs)")

    fake_module = mock.Mock()
    fake_module.RealBaseFailingWorkLRP = RealBaseFailingWorkLRP

    row = LRPStatus.objects.create(start_time=1.0, current_status="working", process_id=1234)

    monkeypatch.setattr(settings, "TEMP_FILES_DIR", str(tmp_path))
    monkeypatch.setattr(_mod, "FitPool", mock.Mock())  # don't spawn a real pool
    monkeypatch.setattr(cp.importlib, "import_module", lambda _path: fake_module)
    monkeypatch.setattr(cp, "time", mock.Mock())  # skip the 1s post-work sleep

    payload = cp.ChildPayload(
        lrp_class_path="fake.module.RealBaseFailingWorkLRP",
        session_key_data="",
        session_key_functionfinder="",
        dimensionality=2,
        renice_level=10,
        data_object=None,
        equation=None,
        status_row_pk=row.pk,
    )

    cp._run_fit_child(payload)

    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert reloaded.process_id == 0  # gate released by the finally
    # The error artifact must be LINKED, not orphaned on disk.
    assert reloaded.redirect_to_results.endswith(".html")
    assert os.path.exists(reloaded.redirect_to_results)
    assert reloaded.state == LRPStatus.State.TERMINAL
    assert reloaded.current_status  # carries the user-facing error text
