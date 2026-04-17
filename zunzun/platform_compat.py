"""Platform-specific shim layer for zunzunsite3.

Consolidates all calls that vary across Linux/macOS/Windows so the
rest of the codebase can stay platform-agnostic. Delegates to psutil
and subprocess.run for the cross-platform implementations.

Named platform_compat (not platform) to avoid shadowing the stdlib
platform module.
"""
from __future__ import annotations

import functools
import glob
import logging
import multiprocessing
import os
import shutil
import subprocess
from pathlib import Path

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


def reap_completed_children() -> None:
    """Reap any completed multiprocessing children of the current process.

    Replaces the psutil.STATUS_ZOMBIE loop in views.CommonToAllViews.
    On Unix, joins any zombie children so they don't linger in the
    process table. On Windows, this is effectively a no-op (Windows
    doesn't produce zombies) but the call is safe and cheap.
    """
    for child in multiprocessing.active_children():
        if not child.is_alive():
            child.join(timeout=0)


def set_process_niceness(pid: int, niceness: int) -> None:
    """Set the OS-level scheduling priority of a process.

    On Unix, delegates to the standard Unix nice value (-20 to 19).
    On Windows, psutil translates to priority classes internally:
      < 0    → HIGH_PRIORITY_CLASS
      0      → NORMAL_PRIORITY_CLASS
      1-9    → BELOW_NORMAL_PRIORITY_CLASS
      >= 10  → IDLE_PRIORITY_CLASS

    Silently tolerates AccessDenied — failing to renice is not fatal,
    the child just runs at the default priority.
    """
    try:
        psutil.Process(pid).nice(niceness)
    except (psutil.AccessDenied, psutil.NoSuchProcess) as e:
        _logger.info("set_process_niceness(%d, %d) failed: %s", pid, niceness, e)


def run_tool(binary: str, args: list[str], stdout_file: Path | None = None) -> int:
    """Run an external command; return its exit code.

    Replaces os.popen() shellouts. Uses subprocess.run with an argument
    list (not shell=True) which eliminates shell-injection risk from
    filenames containing special characters.

    If stdout_file is given, stdout is redirected there (replacing the
    shell's '> file' operator). Otherwise stdout is inherited.

    Raises FileNotFoundError if the binary is not on PATH.
    """
    stdout_target = None
    if stdout_file is not None:
        stdout_target = open(stdout_file, "wb")
    try:
        result = subprocess.run(
            [binary, *args],
            stdout=stdout_target,
            check=False,
        )
        return result.returncode
    finally:
        if stdout_target is not None:
            stdout_target.close()


def remove_files_matching(pattern: str) -> int:
    """Delete every file matching a glob pattern; return count removed.

    Replaces os.popen('rm path__*') calls. Silently tolerates missing
    files (matching the `rm -f` semantics of the original).
    """
    count = 0
    for path in glob.glob(pattern):
        try:
            os.remove(path)
            count += 1
        except OSError as e:
            _logger.info("remove_files_matching: failed to remove %s: %s", path, e)
    return count


REQUIRED_BINARIES = ("mogrify", "gifsicle")


def ensure_external_binaries() -> list[str]:
    """Report which optional external binaries are missing from PATH.

    mogrify (part of ImageMagick) and gifsicle are used in
    ReportsAndGraphs.py to produce animated GIF output. They are not
    strictly required — fits and PDFs work without them — but 3D
    animations won't render if they're absent.

    Returns the list of missing binary names. Caller decides whether
    to warn (log) or fail (raise).
    """
    missing = []
    for binary in REQUIRED_BINARIES:
        if shutil.which(binary) is None:
            missing.append(binary)
    return missing
