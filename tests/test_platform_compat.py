"""Unit tests for zunzun.platform_compat.

These tests do not require Django. They cover the cross-platform
abstraction layer that replaces /proc, vmstat, os.popen, etc.
"""
from unittest import mock

import pytest


def test_get_loadavg_returns_three_floats():
    from zunzun import platform_compat
    result = platform_compat.get_loadavg()
    assert isinstance(result, tuple)
    assert len(result) == 3
    assert all(isinstance(x, float) for x in result)
    assert all(x >= 0.0 for x in result)


def test_get_loadavg_unavailable_returns_zero_tuple():
    from zunzun import platform_compat
    with mock.patch("zunzun.platform_compat.psutil.getloadavg",
                    side_effect=AttributeError("not available")):
        result = platform_compat.get_loadavg()
        assert result == (0.0, 0.0, 0.0)


def test_get_loadavg_logs_warning_once(caplog):
    """The fallback path logs exactly once per process, not once per call."""
    import logging
    from zunzun import platform_compat

    # Re-arm the lru_cache since earlier tests may have consumed it
    platform_compat._warn_loadavg_unavailable.cache_clear()

    with mock.patch("zunzun.platform_compat.psutil.getloadavg",
                    side_effect=AttributeError("not available")):
        with caplog.at_level(logging.WARNING, logger="zunzun.platform_compat"):
            platform_compat.get_loadavg()
            platform_compat.get_loadavg()
            platform_compat.get_loadavg()

    # Exactly one warning record despite three calls
    matching = [r for r in caplog.records
                if "psutil.getloadavg() unavailable" in r.getMessage()]
    assert len(matching) == 1


def test_get_parallel_process_count_returns_at_least_one():
    from zunzun import platform_compat
    n = platform_compat.get_parallel_process_count()
    assert isinstance(n, int)
    assert n >= 1


def test_get_parallel_process_count_respects_cpu_cap():
    from zunzun import platform_compat
    n = platform_compat.get_parallel_process_count(cpu_cap=2)
    assert 1 <= n <= 2


def test_get_parallel_process_count_under_high_load():
    from zunzun import platform_compat
    import multiprocessing
    cpu = multiprocessing.cpu_count()
    # Simulate extreme load — should throttle to <=3 per spec behavior
    with mock.patch("zunzun.platform_compat.psutil.getloadavg",
                    return_value=(cpu + 2.0, cpu + 2.0, cpu + 2.0)):
        n = platform_compat.get_parallel_process_count()
        assert n <= 3
