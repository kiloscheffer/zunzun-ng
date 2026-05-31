"""Platform-specific shim layer for zunzun-ng.

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
        "platform_compat.get_loadavg: psutil.getloadavg() unavailable; returning (0.0, 0.0, 0.0)"
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
    except AttributeError, OSError:
        _warn_loadavg_unavailable()
        return (0.0, 0.0, 0.0)


def get_parallel_process_count(cpu_cap: int | None = None) -> int:
    """Return the number of worker processes to use for parallel fitting.

    Resolution order for the per-fit worker cap:
      1. ``cpu_cap`` argument (legacy override, mostly used in tests).
      2. ``ZUNZUN_MAX_WORKERS`` env var (delegated to
         ``zunzun.parallel_pool.resolve_max_workers``).
      3. ``settings.MAX_PARALLEL_WORKERS``.
      4. Auto-detect: ``min(cpu_count, available_RAM_KiB / 200_000)``.

    Then throttles down under high system load (load1 > cpu_count + 0.5/1.0/1.5
    knocks the count down to 3/2/1 respectively).

    Returns at least 1. The 4-worker hard cap on spawn platforms that
    previously lived here was removed when persistent worker pools made
    the per-chunk spawn cost a non-issue.
    """
    # Late import to avoid circular dependency (parallel_pool imports nothing
    # from platform_compat at module scope, but be explicit).
    from zunzun.parallel_pool import resolve_max_workers

    cpu_count = multiprocessing.cpu_count()

    n = resolve_max_workers(explicit=cpu_cap)

    # Cross-check against the historical mem-estimate path for callers
    # that bypass resolve_max_workers (e.g., explicit cpu_cap might be
    # generous). 200_000 KiB ≈ 200 MB per worker is the conservative
    # observed-ceiling on Python 3.14 + numpy 2.4 + scipy 1.17 (down from
    # the original 750_000 KiB pessimistic estimate that drove the 4-cap).
    mem = psutil.virtual_memory()
    mem_kib_available = mem.available / 1024.0
    mem_ceiling = max(1, int(mem_kib_available / 200_000))
    n = min(n, mem_ceiling)

    load1, _, _ = get_loadavg()
    if load1 > (cpu_count + 1.5) and n > 1:
        n = 1
    elif load1 > (cpu_count + 1.0) and n > 2:
        n = 2
    elif load1 > (cpu_count + 0.5) and n > 3:
        n = 3

    return max(1, n)


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


def pid_is_alive(pid: int) -> bool:
    """True iff a process with ``pid`` exists on this host and is not a zombie.

    Backstop for the status views: a fit child that vanished WITHOUT finalizing
    its ``LRPStatus`` row (SIGKILL / OOM kill / segfault, or a terminal status
    write that itself failed under DB lock) leaves the row showing an
    in-progress fit forever — ``process_id`` set, ``completed`` False — so the
    poll loop never ends and the per-user gate's ``is_active`` check blocks the
    user's retry for up to 300s. The views call this to detect that the owning
    pid is gone and finalize the row instead of polling indefinitely.

    A zombie (Unix: exited but not yet reaped) counts as NOT alive — the child
    has finished and is only awaiting reap, so the backstop fires on the next
    poll rather than waiting for ``reap_completed_children``. On Windows there
    are no zombies and ``status()`` simply never returns ``STATUS_ZOMBIE``.
    ``pid`` 0 is the cleared sentinel, never a live child, and returns False
    without a syscall. Valid only because the spawn children are co-located
    with the web worker on the same host. A reused pid (rare) makes this MISS
    (a live unrelated process leaves the fit polling as before), never misfire.
    """
    if not pid:
        return False
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        # AccessDenied or any other psutil failure on a foreign pid: err toward
        # "alive" so we never falsely finalize a fit that is actually running.
        return True


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
