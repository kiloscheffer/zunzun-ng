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
