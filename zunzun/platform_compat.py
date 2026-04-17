"""Platform-specific shim layer for zunzunsite3.

Consolidates all calls that vary across Linux/macOS/Windows so the
rest of the codebase can stay platform-agnostic. Delegates to psutil
and subprocess.run for the cross-platform implementations.

Named platform_compat (not platform) to avoid shadowing the stdlib
platform module.
"""
from __future__ import annotations

import logging

import psutil

_logger = logging.getLogger(__name__)
_loadavg_warned = False


def get_loadavg() -> tuple[float, float, float]:
    """1/5/15-minute load average across all platforms.

    On Linux/macOS uses psutil.getloadavg() which wraps os.getloadavg().
    On Windows, psutil simulates a rolling average. If unavailable
    (e.g. very old psutil or unsupported platform), logs a one-time
    warning and returns zeros.
    """
    global _loadavg_warned
    try:
        one, five, fifteen = psutil.getloadavg()
        return (float(one), float(five), float(fifteen))
    except (AttributeError, OSError):
        if not _loadavg_warned:
            _logger.warning(
                "platform_compat.get_loadavg: psutil.getloadavg() unavailable; "
                "returning (0, 0, 0)"
            )
            _loadavg_warned = True
        return (0.0, 0.0, 0.0)
