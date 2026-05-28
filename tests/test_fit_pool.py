"""Tests for FitPool — the per-fit persistent worker pool."""

import os
import time
from unittest import mock

import pytest

# Module-level worker functions (must be picklable for spawn)


def _square(x):
    return x * x


def _raises(x):
    raise ValueError(f"worker boom on {x}")


def _slow(x):
    time.sleep(0.5)
    return x


def _exit_immediately(x):
    """Simulate a worker that dies silently (not a Python exception)."""
    os._exit(1)


def test_fit_pool_size_uses_resolve_max_workers():
    from zunzun.parallel_pool import FitPool

    with FitPool(max_workers=2) as pool:
        assert pool.max_workers == 2


def test_fit_pool_size_defaults_to_resolver(monkeypatch):
    """No explicit arg → resolver picks (subject to clamps)."""
    monkeypatch.delenv("ZUNZUN_MAX_WORKERS", raising=False)
    from zunzun.parallel_pool import FitPool

    with FitPool() as pool:
        assert pool.max_workers >= 1


def test_fit_pool_submit_returns_future_with_result():
    from zunzun.parallel_pool import FitPool

    with FitPool(max_workers=2) as pool:
        fut = pool.submit(_square, 5)
        assert fut.result(timeout=30) == 25


def test_fit_pool_submit_many_yields_all_results():
    from zunzun.parallel_pool import FitPool

    with FitPool(max_workers=2) as pool:
        results = sorted(pool.submit_many(_square, [1, 2, 3, 4]))
    assert results == [1, 4, 9, 16]


def test_fit_pool_submit_many_calls_progress_callback():
    from zunzun.parallel_pool import FitPool

    calls = []

    def progress(done, total):
        calls.append((done, total))

    with FitPool(max_workers=2) as pool:
        list(pool.submit_many(_square, [1, 2, 3], progress=progress))

    # Progress called once per completion (3 items → 3 calls)
    assert len(calls) == 3
    # Final call says all-done
    assert calls[-1] == (3, 3)


def test_fit_pool_submit_many_empty_input_returns_nothing():
    from zunzun.parallel_pool import FitPool

    with FitPool(max_workers=2) as pool:
        results = list(pool.submit_many(_square, []))
    assert results == []


def test_fit_pool_propagates_worker_exception():
    from zunzun.parallel_pool import FitPool

    with FitPool(max_workers=2) as pool:
        fut = pool.submit(_raises, 7)
        with pytest.raises(ValueError, match="worker boom on 7"):
            fut.result(timeout=30)


def test_fit_pool_submit_many_propagates_first_exception():
    from zunzun.parallel_pool import FitPool

    with FitPool(max_workers=2) as pool:
        with pytest.raises(ValueError, match="worker boom"):
            list(pool.submit_many(_raises, [1, 2]))


def test_fit_pool_shutdown_idempotent():
    from zunzun.parallel_pool import FitPool

    pool = FitPool(max_workers=2)
    pool.shutdown(wait=True)
    pool.shutdown(wait=True)  # second call must not raise


def test_fit_pool_shutdown_cancel_futures_stops_pending():
    from zunzun.parallel_pool import FitPool

    pool = FitPool(max_workers=1)  # one worker forces serialization
    futures = [pool.submit(_slow, i) for i in range(5)]
    pool.shutdown(wait=False, cancel_futures=True)
    # The 1-worker pool can only execute one item at a time; items 1-4
    # stay pending while item 0 runs (and item 0 may finish or be
    # uncancellable depending on timing). At least 3 of the 4 pending
    # items must be cancelled by the pre-cancel loop.
    cancelled = sum(1 for f in futures if f.cancelled())
    assert cancelled >= 3


def test_fit_pool_context_manager_shuts_down():
    from zunzun.parallel_pool import FitPool

    with FitPool(max_workers=2) as pool:
        fut = pool.submit(_square, 3)
        assert fut.result(timeout=30) == 9
    # After context exit, submit should fail with RuntimeError
    with pytest.raises(RuntimeError):
        pool.submit(_square, 4)


def test_fit_pool_logs_creation():
    import logging

    from zunzun.parallel_pool import FitPool

    with mock.patch.object(logging.getLogger("zunzun.parallel_pool"), "info") as mock_info:
        with FitPool(max_workers=2):
            pass
    # At least one INFO call mentioning FitPool + max_workers
    assert any(
        "FitPool" in str(call) and "max_workers" in str(call) for call in mock_info.call_args_list
    )


def test_fit_pool_broken_pool_surfaces_exception():
    """When a worker dies silently (not via raising), the pool surfaces
    BrokenProcessPool rather than hanging — this is the key advantage over
    multiprocessing.Pool which would hang in this scenario."""
    import concurrent.futures.process

    from zunzun.parallel_pool import FitPool

    with FitPool(max_workers=2) as pool:
        fut = pool.submit(_exit_immediately, 1)
        with pytest.raises(concurrent.futures.process.BrokenProcessPool):
            fut.result(timeout=30)


def test_fit_pool_sets_blas_thread_env_when_unset(monkeypatch):
    """FitPool defaults BLAS thread vars to 1 so spawn workers don't blow up
    their thread pools on big-core machines. The setdefault pattern means
    these are set when not already configured."""
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    monkeypatch.delenv("OPENBLAS_NUM_THREADS", raising=False)
    monkeypatch.delenv("MKL_NUM_THREADS", raising=False)

    from zunzun.parallel_pool import FitPool

    with FitPool(max_workers=2):
        assert os.environ.get("OMP_NUM_THREADS") == "1"
        assert os.environ.get("OPENBLAS_NUM_THREADS") == "1"
        assert os.environ.get("MKL_NUM_THREADS") == "1"


def test_fit_pool_respects_existing_blas_thread_env(monkeypatch):
    """If a user has explicitly set OMP_NUM_THREADS (e.g., to tune for a
    large-matrix single fit), FitPool must not override it."""
    monkeypatch.setenv("OMP_NUM_THREADS", "4")
    monkeypatch.delenv("OPENBLAS_NUM_THREADS", raising=False)

    from zunzun.parallel_pool import FitPool

    with FitPool(max_workers=2):
        # User's explicit value preserved
        assert os.environ.get("OMP_NUM_THREADS") == "4"
        # Unset vars still get defaulted
        assert os.environ.get("OPENBLAS_NUM_THREADS") == "1"


def test_fit_pool_treats_empty_string_blas_env_as_unset(monkeypatch):
    """An empty-string OMP_NUM_THREADS (which OpenBLAS treats as 'unset, use
    cpu_count') must be replaced with '1', not preserved. setdefault would
    incorrectly preserve it."""
    monkeypatch.setenv("OMP_NUM_THREADS", "")

    from zunzun.parallel_pool import FitPool

    with FitPool(max_workers=2):
        assert os.environ.get("OMP_NUM_THREADS") == "1"


# Module-level worker functions for initializer tests (must be picklable for spawn)


def _set_worker_marker(value):
    """Test initializer: store a marker in module-level state."""
    import zunzun.parallel_pool as pp

    pp._test_worker_marker = value


def _read_worker_marker(_unused):
    """Worker task: read whatever the initializer stashed."""
    import zunzun.parallel_pool as pp

    return getattr(pp, "_test_worker_marker", None)


def test_fit_pool_initializer_installs_per_worker_state():
    """FitPool can pass initializer/initargs through to ProcessPoolExecutor.
    The initializer runs once per worker; subsequent tasks read whatever
    the initializer stashed in module-level state."""
    from zunzun.parallel_pool import FitPool

    with FitPool(
        max_workers=2,
        initializer=_set_worker_marker,
        initargs=("sentinel-value",),
    ) as pool:
        results = list(pool.submit_many(_read_worker_marker, [1, 2, 3, 4]))

    # All four tasks should observe the marker that the initializer installed
    assert all(r == "sentinel-value" for r in results), results


def test_fit_pool_initializer_defaults_to_none():
    """Backward compatibility: callers that don't pass initializer get the
    legacy behavior (no initializer, plain executor)."""
    from zunzun.parallel_pool import FitPool

    with FitPool(max_workers=2) as pool:
        # If no initializer, _test_worker_marker is not set in workers
        results = list(pool.submit_many(_read_worker_marker, [1, 2]))

    assert all(r is None for r in results), results
