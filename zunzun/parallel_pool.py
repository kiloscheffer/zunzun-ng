"""Persistent worker pool for parallel fits inside an LRP child process.

Wraps concurrent.futures.ProcessPoolExecutor with spawn context, centralizing:
- Worker count resolution (ZUNZUN_MAX_WORKERS env > settings > auto-detect)
- Progress callback for 1-Hz status-session updates
- Graceful shutdown including cancel_futures for abandoned fits

Lifecycle: created in StatusMonitoredLongRunningProcessPage.PerformAllWork()
at fit start, shut down in the `finally` block. Pool workers are sub-children
of the LRP child, so they die when the fit ends.
"""

from __future__ import annotations

import concurrent.futures
import logging
import multiprocessing
import os
from typing import Any, Callable, Iterable, Iterator

import psutil

_logger = logging.getLogger(__name__)


def resolve_max_workers(explicit: int | None = None) -> int:
    """Resolve the per-fit worker count.

    Order of precedence (first valid wins):
      1. ``explicit`` argument (mostly used in tests).
      2. ``ZUNZUN_MAX_WORKERS`` env var (must be positive int).
      3. ``settings.MAX_PARALLEL_WORKERS`` (must be positive int).
      4. Auto-detect: ``min(cpu_count, available_RAM_KiB / 200_000)``.

    Result is always clamped to ``min(value, cpu_count, available_RAM_KiB / 200_000)``
    so an env-var misconfiguration cannot exceed hardware capacity. Always
    returns at least 1.
    """
    cpu_count = multiprocessing.cpu_count()
    mem_kib_available = psutil.virtual_memory().available / 1024.0
    ram_budget = max(1, int(mem_kib_available / 200_000))
    hardware_ceiling = max(1, min(cpu_count, ram_budget))

    if explicit is not None and explicit > 0:
        return max(1, min(explicit, hardware_ceiling))

    env_value = os.environ.get("ZUNZUN_MAX_WORKERS", "").strip()
    if env_value:
        try:
            n = int(env_value)
            if n > 0:
                return max(1, min(n, hardware_ceiling))
        except ValueError:
            _logger.warning(
                "ZUNZUN_MAX_WORKERS=%r is not a valid positive integer; ignoring", env_value
            )

    try:
        import settings

        setting_value = getattr(settings, "MAX_PARALLEL_WORKERS", None)
        if setting_value is not None and setting_value > 0:
            return max(1, min(setting_value, hardware_ceiling))
    except ImportError:
        pass

    return hardware_ceiling


class FitPool:
    """Persistent ProcessPoolExecutor for parallel fits within one LRP child.

    Uses spawn context (cross-platform). Workers pay the import cost ONCE
    at pool creation, then are reused across all submit() / submit_many()
    calls until shutdown.

    Lifecycle: typical use is
        with FitPool() as pool:
            pool.submit(fn, *args)        # individual future tracking
            pool.submit_many(fn, items)   # ordered iteration with progress
    or owned as an instance attribute on a long-lived object:
        self.fit_pool = FitPool()
        ...
        finally:
            if self.fit_pool:
                self.fit_pool.shutdown(wait=True)
    """

    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = resolve_max_workers(max_workers)
        ctx = multiprocessing.get_context("spawn")
        self._executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=self.max_workers,
            mp_context=ctx,
        )
        self._shutdown = False
        _logger.info(
            "FitPool created: max_workers=%d (cpu_count=%d)",
            self.max_workers,
            multiprocessing.cpu_count(),
        )

    def submit(
        self, fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> "concurrent.futures.Future[Any]":
        """Submit one callable; return a Future. Raises RuntimeError if the
        pool has been shut down."""
        return self._executor.submit(fn, *args, **kwargs)

    def submit_many(
        self,
        fn: Callable[..., Any],
        items: Iterable[Any],
        *extra_args: Any,
        progress: Callable[[int, int], None] | None = None,
    ) -> Iterator[Any]:
        """Submit fn(item, *extra_args) for each item; yield results in
        completion order. Optional ``progress(done, total)`` callback fires
        once per completion.

        Worker exceptions propagate on result()."""
        items_list = list(items)
        total = len(items_list)
        if total == 0:
            return
        futures = [self._executor.submit(fn, item, *extra_args) for item in items_list]
        done_count = 0
        for fut in concurrent.futures.as_completed(futures):
            done_count += 1
            if progress is not None:
                try:
                    progress(done_count, total)
                except Exception:
                    _logger.exception("FitPool progress callback raised")
            yield fut.result()

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """Shut down the underlying executor. Idempotent.

        When cancel_futures=True, pending work items are cancelled
        synchronously before the executor shutdown so that callers can
        inspect future.cancelled() immediately after this call returns,
        regardless of the wait flag.
        """
        if self._shutdown:
            return
        self._shutdown = True
        if cancel_futures:
            # Cancel any futures still sitting in _pending_work_items before
            # handing off to the executor's own shutdown logic.  The executor
            # also sets _cancel_pending_futures, but only acts on it in its
            # manager thread, which may not have run yet when wait=False.
            pending = getattr(self._executor, "_pending_work_items", {})
            for work_item in list(pending.values()):
                work_item.future.cancel()
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def __enter__(self) -> "FitPool":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.shutdown(wait=True)
