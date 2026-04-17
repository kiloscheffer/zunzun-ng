"""Platform-specific shim layer for zunzunsite3.

Consolidates all calls that vary across Linux/macOS/Windows so the
rest of the codebase can stay platform-agnostic. Delegates to psutil
and subprocess.run for the cross-platform implementations.

Named platform_compat (not platform) to avoid shadowing the stdlib
platform module.
"""
from __future__ import annotations

import functools
import logging
import multiprocessing

import psutil

_logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _warn_loadavg_unavailable() -> None:
    """Emit the loadavg-unavailable warning exactly once per process.

    Use .cache_clear() in tests to re-arm the warning.
    """
    _logger.warning(
        "platform_compat.get_loadavg: psutil.getloadavg() unavailable; "
        "returning (0.0, 0.0, 0.0)"
    )


def get_loadavg() -> tuple[float, float, float]:
    """1/5/15-minute load average across all platforms.

    On Linux/macOS uses psutil.getloadavg() which wraps os.getloadavg().
    On Windows, psutil simulates a rolling average. If unavailable
    (e.g. very old psutil, an unsupported platform, or an OSError
    reading /proc/loadavg), logs a one-time warning and returns zeros.
    """
    try:
        one, five, fifteen = psutil.getloadavg()
        return (float(one), float(five), float(fifteen))
    except (AttributeError, OSError):
        _warn_loadavg_unavailable()
        return (0.0, 0.0, 0.0)


def get_parallel_process_count(cpu_cap: int | None = None) -> int:
    """Return the number of worker processes to use for parallel fitting.

    Throttles based on available memory and CPU load, matching the
    behavior of the original StatusMonitoredLongRunningProcessPage.GetParallelProcessCount()
    but driven by psutil instead of /proc/loadavg and vmstat.

    Heuristic:
    - Start with free+cached memory / 80 MB
    - Cap at min(cpu_cap, cpu_count)
    - Reduce further if load average is >= cpu_count + 0.5/1.0/1.5
    - Floor at 1
    """
    cpu_count = multiprocessing.cpu_count()
    effective_cap = min(cpu_cap, cpu_count) if cpu_cap is not None else cpu_count

    # Memory-based ceiling: free + cached, in KiB, divided by 80 MB
    mem = psutil.virtual_memory()
    mem_kib_available = (mem.available) / 1024.0
    n = int(mem_kib_available / 80000.0)

    n = min(n, effective_cap)
    n = max(n, 1)

    # Load-based throttle
    load1, _, _ = get_loadavg()
    if load1 > (cpu_count + 1.5) and n > 1:
        n = 1
    elif load1 > (cpu_count + 1.0) and n > 2:
        n = 2
    elif load1 > (cpu_count + 0.5) and n > 3:
        n = 3

    return n
