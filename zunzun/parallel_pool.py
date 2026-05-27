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

import logging
import multiprocessing
import os

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
