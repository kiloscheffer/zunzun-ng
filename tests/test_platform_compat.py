"""Unit tests for zunzun.platform_compat.

These tests do not require Django. They cover the cross-platform
abstraction layer that replaces /proc, vmstat, os.popen, etc.
"""
import sys
from pathlib import Path
from unittest import mock

import psutil
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


def test_set_process_niceness_calls_psutil():
    from zunzun import platform_compat
    fake_proc = mock.MagicMock()
    with mock.patch("zunzun.platform_compat.psutil.Process", return_value=fake_proc):
        platform_compat.set_process_niceness(12345, 10)
    fake_proc.nice.assert_called_once_with(10)


def test_set_process_niceness_silent_on_access_denied():
    from zunzun import platform_compat
    fake_proc = mock.MagicMock()
    fake_proc.nice.side_effect = psutil.AccessDenied()
    with mock.patch("zunzun.platform_compat.psutil.Process", return_value=fake_proc):
        # Should not raise — niceness failure is not fatal
        platform_compat.set_process_niceness(12345, 10)


def _noop_child():
    """Top-level helper for spawn picklability. Module-level, not nested."""
    pass


def test_reap_completed_children_joins_finished_processes():
    from zunzun import platform_compat
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    p = ctx.Process(target=_noop_child, args=())
    p.start()
    p.join(timeout=5)  # wait for it to finish
    assert not p.is_alive()

    # Should be a no-op because the process is already joined
    platform_compat.reap_completed_children()
    # No assertion — just that it doesn't raise


def test_run_tool_returns_exit_code_on_success(tmp_path):
    from zunzun import platform_compat
    import sys
    # Use python itself as a known-available cross-platform binary
    exit_code = platform_compat.run_tool(sys.executable, ["-c", "import sys; sys.exit(0)"])
    assert exit_code == 0


def test_run_tool_returns_nonzero_on_failure():
    from zunzun import platform_compat
    import sys
    exit_code = platform_compat.run_tool(sys.executable, ["-c", "import sys; sys.exit(7)"])
    assert exit_code == 7


def test_run_tool_redirects_stdout_to_file(tmp_path):
    from zunzun import platform_compat
    import sys
    out = tmp_path / "out.txt"
    platform_compat.run_tool(
        sys.executable,
        ["-c", "print('hello')"],
        stdout_file=out,
    )
    assert out.read_text().strip() == "hello"


def test_run_tool_raises_on_missing_binary():
    from zunzun import platform_compat
    with pytest.raises(FileNotFoundError):
        platform_compat.run_tool("definitely-not-a-real-binary", [])


def test_remove_files_matching_deletes_matches(tmp_path):
    from zunzun import platform_compat
    (tmp_path / "frame__01.gif").write_text("x")
    (tmp_path / "frame__02.gif").write_text("x")
    (tmp_path / "other.png").write_text("x")
    count = platform_compat.remove_files_matching(str(tmp_path / "frame__*"))
    assert count == 2
    assert not (tmp_path / "frame__01.gif").exists()
    assert not (tmp_path / "frame__02.gif").exists()
    assert (tmp_path / "other.png").exists()


def test_remove_files_matching_tolerates_no_matches(tmp_path):
    from zunzun import platform_compat
    count = platform_compat.remove_files_matching(str(tmp_path / "nothing__*"))
    assert count == 0


def test_ensure_external_binaries_returns_missing():
    from zunzun import platform_compat

    def fake_which(name):
        # Pretend only mogrify is present
        return "/usr/bin/mogrify" if name == "mogrify" else None

    with mock.patch("zunzun.platform_compat.shutil.which", side_effect=fake_which):
        missing = platform_compat.ensure_external_binaries()
    assert missing == ["gifsicle"]


def test_ensure_external_binaries_returns_empty_when_all_present():
    from zunzun import platform_compat
    with mock.patch("zunzun.platform_compat.shutil.which", return_value="/usr/bin/anything"):
        missing = platform_compat.ensure_external_binaries()
    assert missing == []
