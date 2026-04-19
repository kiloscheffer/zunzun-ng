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
    - Estimate per-worker memory based on start method (fork ≈ 80 MB
      via copy-on-write; spawn ≈ 750 MB because each worker re-imports
      numpy/scipy/pyeq3 from scratch).
    - Ceiling at available memory / per-worker estimate.
    - Cap at min(cpu_cap, cpu_count). On platforms that use spawn by
      default (Windows, macOS), hard-cap at 4 to keep total VM usage
      tractable even on high-core machines with modest RAM.
    - Reduce under high load.
    - Floor at 1.
    """
    import sys

    cpu_count = multiprocessing.cpu_count()

    # Pick the default multiprocessing start method for this platform.
    # "fork" on Linux (cheap), "spawn" on Windows + macOS (expensive).
    default_start = multiprocessing.get_start_method(allow_none=False)
    uses_spawn = default_start != "fork"

    # Per-worker memory cost scales dramatically with the start method.
    per_worker_kib = 750_000 if uses_spawn else 80_000

    # On spawn platforms, hard-cap at 4 workers by default — the memory
    # math alone can permit more, but pagefile pressure and process-startup
    # overhead make high worker counts counterproductive. Callers that
    # really want more can pass cpu_cap explicitly.
    platform_ceiling = 4 if uses_spawn else cpu_count

    if cpu_cap is None:
        effective_cap = min(platform_ceiling, cpu_count)
    else:
        effective_cap = min(cpu_cap, cpu_count)

    mem = psutil.virtual_memory()
    mem_kib_available = mem.available / 1024.0
    n = int(mem_kib_available / per_worker_kib)

    n = min(n, effective_cap)
    n = max(n, 1)

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


def run_tool(binary: str | list[str], args: list[str], stdout_file: Path | None = None) -> int:
    """Run an external command; return its exit code.

    Replaces os.popen() shellouts. Uses subprocess.run with an argument
    list (not shell=True) which eliminates shell-injection risk from
    filenames containing special characters.

    `binary` may be either a string (single executable name/path) or a list
    (e.g. ["magick", "mogrify"] for ImageMagick 7's subcommand form).
    In the list case, every element is prepended to the command before `args`.

    If stdout_file is given, stdout is redirected there (replacing the
    shell's '> file' operator). Otherwise stdout is inherited.

    Raises FileNotFoundError if the binary is not on PATH.
    """
    if isinstance(binary, str):
        cmd = [binary, *args]
    else:
        cmd = [*binary, *args]
    stdout_target = None
    if stdout_file is not None:
        stdout_target = open(stdout_file, "wb")
    try:
        result = subprocess.run(cmd, stdout=stdout_target, check=False)
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


def ensure_external_binaries() -> list[str]:
    """Report which optional external binaries are missing from PATH.

    Reserved as a hook for future platform-specific binary checks. As
    of 2026-04-19 the codebase has no non-Python runtime dependencies
    (animated GIF output was migrated to matplotlib's PillowWriter,
    replacing ImageMagick's mogrify and gifsicle). The function still
    returns a list so apps.py's AppConfig.ready() warning infrastructure
    stays in place for future use.

    Returns the list of missing binary names. Caller decides whether
    to warn (log) or fail (raise).
    """
    return []
