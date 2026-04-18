# Cross-platform Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make zunzunsite3 run natively on Linux, macOS, and Windows for development and production, by replacing `os.fork()` with `multiprocessing.Process(spawn)`, abstracting platform-specific calls (`/proc`, `vmstat`, `os.getloadavg`, POSIX shellouts) into a `platform_compat` module, and documenting per-OS deployment recipes using Waitress as the production server.

**Architecture:** Spawn-based child processes replace the fork pattern, with a picklable `ChildPayload` dataclass carrying the minimum state needed for `PerformAllWork()` across the process boundary. All platform-specific calls are consolidated into `zunzun/platform_compat.py` which delegates to `psutil` and `subprocess.run` for cross-platform behavior. Waitress replaces uwsgi/gunicorn as the recommended WSGI server on all platforms because its thread-based worker model works natively on Windows.

**Tech Stack:** Python 3.11, Django 2.2.28, multiprocessing (spawn context), psutil, Waitress, pytest + pytest-django, uv for dependency management.

**Reference:** Design spec at `docs/superpowers/specs/2026-04-17-cross-platform-design.md` (commit 874b6de). The spec has been updated post-execution with a §12 "Lessons learned" section — read it before attempting a similar migration.

---

## ⚠ Lessons from execution (added 2026-04-18)

This plan was executed through Phase 4 (smoke test pass) on a Windows 11 box. Several task code blocks below have bugs or missing pieces discovered during execution. If you are re-running this plan, apply these corrections:

1. **Task 4 — `get_parallel_process_count`** must be platform-aware. The plan's heuristic (80 MB per worker) is accurate only for Linux fork; Windows/macOS spawn workers are ~750 MB each. Additionally, hard-cap at 4 workers on spawn platforms to avoid pagefile exhaustion. See spec §12.2.

2. **Task 19 — `_run_fit_child`** must bootstrap Django at the top of the function before any ORM access:
   ```python
   os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
   import django
   django.setup()
   ```
   Without this, the child raises `AppRegistryNotReady` on first `SessionStore` save. See spec §12.1.

3. **Task 21 — `FittingBaseClass.build_child_payload`** must also carry `pdfTitleHTML` and `webFormName` (both set on `self`, not `self.dataObject`, during form processing). Missing these causes `AttributeError` in the child's `CreateReportPDF`. See spec §12.3.

4. **Task 22 — Fit* subclass overrides** should read fields from `self.boundForm.equation.X` (not `self.dataObject.X` as the plan suggests). The Task 22 implementer caught this during execution. See commit `41c35de`.

5. **New task — `normed` → `density`.** Fix `zunzun/LongRunningProcess/MatplotlibGraphs_2D.py:145`: matplotlib 3.2+ removed the `normed=` kwarg (now `density=`). Not a migration issue per se, but exposed by uv-locking to modern matplotlib. See spec §12.4.

6. **Task 28 — `scripts/smoke_test.py`** readiness probe: use `socket.create_connection`, NOT `requests.get`. The HTTP-based probe poisons session cookies because `HomePageView` is `@cache_page`-decorated. Also: timeout = 600s (not 240s), and assert on *structural* markers (`"Coefficient and Fit Statistics"`, `"Minimum:"`, `"Maximum:"`), not FunkLoad's hardcoded numerical coefficients which are stale under modern numpy/scipy/pyeq3. See spec §§12.6, 12.7, 12.8.

7. **Task 32 — dependencies** must include `lxml` in addition to `waitress`. `BeautifulSoup(..., "lxml")` is used in `CreateReportPDF`; bs4 does not transitively install lxml. See spec §12.5.

8. **Task 31 — inner UDF fork** doesn't exist as described. The plan assumed `FitUserDefinedFunction.py` had its own `os.fork()` for isolating user-code compilation. In reality the only `os._exit(0)` there is a hard-abort in an already-spawned child's error path, not an inner fork. Replace with `raise SystemExit(0)`. See commit `df3113a`.

If re-running: fold these corrections into the task code blocks before dispatch. The current plan's code blocks will not work without them.

---

## Global conventions

- **Test command:** `uv run pytest tests/ -v`
- **Django check:** `uv run python manage.py check` (smoke after non-test changes)
- **Commit style:** Short subject matching repo style (no conventional-commit prefixes), body with Co-Authored-By trailer per project CLAUDE.md
- **Per-step commits:** Each TDD task ends with a single commit. Refactor tasks ending in verified-passing tests also commit.
- **Hook awareness:** `.claude/hooks/py_compile_check.py` runs on every `.py` Edit/Write. It blocks commits that introduce syntax errors. No opt-out; fix the syntax if it fires.

## Phasing overview

| Phase | Tasks | Output |
|---|---|---|
| **0 — Foundation** | 1–11 | pytest infra, `platform_compat` module, pickle round-trip spike |
| **1 — Peripheral shims** | 12–18 | All `/proc`/`vmstat`/`popen`/`getloadavg` sites migrated; site still uses `os.fork()` but closer to portable |
| **2 — ChildPayload + spawn (RISKY)** | 19–29 | `LongRunningProcessView` uses `multiprocessing.Process(spawn)`; pickle boundary established |
| **3 — Finish spawn migration** | 30–31 | `HomePageView` housekeeping fork and `FitUserDefinedFunction` inner fork migrated |
| **4 — Waitress + apps.py** | 32–34 | `waitress` added, AppConfig ready-hook warns on missing binaries |
| **5 — Deployment docs** | 35–40 | `docs/deployment/{linux,macos,windows}.md` + README updates |

---

# Phase 0 — Foundation

## Task 1: Add pytest + pytest-django to dev dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject.toml to add pytest dependencies and config**

Edit `pyproject.toml`. In the `[dependency-groups]` → `dev` list, add `pytest` and `pytest-django`. At the bottom of the file, add a `[tool.pytest.ini_options]` section.

Current `dev` group looks like:
```toml
[dependency-groups]
dev = [
    "mypy",
    # Note: FunkLoad ...
]
```

Change to:
```toml
[dependency-groups]
dev = [
    "mypy",
    "pytest>=7.0",
    "pytest-django>=4.5",
    "requests>=2.28",  # for scripts/smoke_test.py in later phases
    # Note: FunkLoad ...
]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "settings"
python_files = ["test_*.py"]
testpaths = ["tests"]
# Don't let pytest try to collect the funkload_tests directory
# (its test files need a live server, not pytest, and importing them fails)
norecursedirs = ["funkload_tests", ".venv", "temp", "session_db"]
```

- [ ] **Step 2: Run `uv sync` to install new deps**

Run: `uv sync`
Expected: new packages install cleanly (pytest, pytest-django, requests and their transitive deps).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
Add pytest, pytest-django, requests to dev dependencies

Enables TDD-style implementation of the cross-platform migration.
pytest-django handles DJANGO_SETTINGS_MODULE and app-registry setup
for tests that touch LRP classes. requests is for the upcoming
scripts/smoke_test.py end-to-end runner.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Create tests/ directory skeleton

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Create the tests/ directory with an __init__.py**

Write empty file: `tests/__init__.py`

- [ ] **Step 2: Create tests/conftest.py**

Write `tests/conftest.py`:
```python
"""Pytest config: guarantee Django is configured before any test imports.

pytest-django normally handles this via DJANGO_SETTINGS_MODULE, but we
keep an explicit django.setup() call here as a belt-and-suspenders in
case a test runs before django_settings is autodiscovered.
"""
import django


def pytest_configure(config):
    django.setup()
```

- [ ] **Step 3: Write a trivial smoke test**

Write `tests/test_smoke.py`:
```python
"""Sanity test: pytest runs, Django is importable, settings are loaded."""
from django.conf import settings


def test_django_settings_loaded():
    assert settings.DEBUG in (True, False)
    assert "zunzun" in settings.INSTALLED_APPS


def test_python_stdlib_available():
    import multiprocessing
    import pickle
    assert multiprocessing.get_all_start_methods()
```

- [ ] **Step 4: Run pytest to verify infrastructure**

Run: `uv run pytest tests/ -v`
Expected: both tests PASS. If you see "no tests collected," verify `testpaths` in `pyproject.toml`.

- [ ] **Step 5: Commit**

```bash
git add tests/__init__.py tests/conftest.py tests/test_smoke.py
git commit -m "$(cat <<'EOF'
Add tests/ directory with pytest + Django setup sanity checks

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Implement platform_compat.get_loadavg (TDD)

**Files:**
- Create: `zunzun/platform_compat.py`
- Create: `tests/test_platform_compat.py`

- [ ] **Step 1: Write failing tests for get_loadavg**

Write `tests/test_platform_compat.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zunzun.platform_compat'`

- [ ] **Step 3: Create zunzun/platform_compat.py with get_loadavg**

Write `zunzun/platform_compat.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add zunzun/platform_compat.py tests/test_platform_compat.py
git commit -m "$(cat <<'EOF'
Add platform_compat.get_loadavg shim

First function in the new zunzun/platform_compat.py module — cross-platform
wrapper around psutil.getloadavg() with graceful fallback to zeros
if unavailable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Implement platform_compat.get_parallel_process_count (TDD)

**Files:**
- Modify: `zunzun/platform_compat.py`
- Modify: `tests/test_platform_compat.py`

- [ ] **Step 1: Add failing tests for get_parallel_process_count**

Append to `tests/test_platform_compat.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: 3 new tests FAIL with `AttributeError: module 'zunzun.platform_compat' has no attribute 'get_parallel_process_count'`

- [ ] **Step 3: Implement get_parallel_process_count**

Append to `zunzun/platform_compat.py`:
```python
import multiprocessing


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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add zunzun/platform_compat.py tests/test_platform_compat.py
git commit -m "$(cat <<'EOF'
Add platform_compat.get_parallel_process_count

Cross-platform replacement for StatusMonitoredLongRunningProcessPage
.GetParallelProcessCount. Same throttling logic (memory ceiling,
CPU cap, load-based reduction) but driven by psutil instead of
parsing vmstat stdout and reading /proc/loadavg.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Implement platform_compat.set_process_niceness (TDD)

**Files:**
- Modify: `zunzun/platform_compat.py`
- Modify: `tests/test_platform_compat.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_platform_compat.py`:
```python
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
```

Also add `import psutil` to the top of the test file if not already present.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: 2 new tests FAIL.

- [ ] **Step 3: Implement set_process_niceness**

Append to `zunzun/platform_compat.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add zunzun/platform_compat.py tests/test_platform_compat.py
git commit -m "$(cat <<'EOF'
Add platform_compat.set_process_niceness

Cross-platform wrapper around psutil.Process(pid).nice(). psutil
handles the Unix nice → Windows priority class translation. Tolerates
AccessDenied silently since reniceing is a best-effort optimization.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Implement platform_compat.reap_completed_children (TDD)

**Files:**
- Modify: `zunzun/platform_compat.py`
- Modify: `tests/test_platform_compat.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_platform_compat.py`:
```python
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


def _noop_child():
    """Top-level helper for spawn picklability. Module-level, not nested."""
    pass
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_platform_compat.py::test_reap_completed_children_joins_finished_processes -v`
Expected: FAIL with `AttributeError: module 'zunzun.platform_compat' has no attribute 'reap_completed_children'`

- [ ] **Step 3: Implement reap_completed_children**

Append to `zunzun/platform_compat.py`:
```python
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
```

- [ ] **Step 4: Run test to verify pass**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add zunzun/platform_compat.py tests/test_platform_compat.py
git commit -m "$(cat <<'EOF'
Add platform_compat.reap_completed_children

Cross-platform replacement for the psutil.STATUS_ZOMBIE sweep in
views.CommonToAllViews. Uses multiprocessing.active_children() +
join(timeout=0), which is a no-op on Windows (no zombies exist)
and a proper cleanup on Unix.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Implement platform_compat.run_tool (TDD)

**Files:**
- Modify: `zunzun/platform_compat.py`
- Modify: `tests/test_platform_compat.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_platform_compat.py`:
```python
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
```

Also add `import sys` and `from pathlib import Path` at the top of the test file if not present.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: 4 new tests FAIL.

- [ ] **Step 3: Implement run_tool**

Append to `zunzun/platform_compat.py`:
```python
import subprocess
from pathlib import Path


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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add zunzun/platform_compat.py tests/test_platform_compat.py
git commit -m "$(cat <<'EOF'
Add platform_compat.run_tool as typed subprocess wrapper

Replaces os.popen() shellouts with subprocess.run using an argument
list. Side-benefit: eliminates the shell-injection surface present in
the current ReportsAndGraphs.py 'os.popen("mogrify " + filename)'
pattern. Supports stdout redirection to a file for cases like
'gifsicle ... > outfile'.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Implement platform_compat.remove_files_matching (TDD)

**Files:**
- Modify: `zunzun/platform_compat.py`
- Modify: `tests/test_platform_compat.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_platform_compat.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: 2 new tests FAIL.

- [ ] **Step 3: Implement remove_files_matching**

Append to `zunzun/platform_compat.py`:
```python
import glob
import os


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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: all 14 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add zunzun/platform_compat.py tests/test_platform_compat.py
git commit -m "$(cat <<'EOF'
Add platform_compat.remove_files_matching

Replaces os.popen('rm path__*') in ReportsAndGraphs.py. Uses
glob + os.remove, which is cross-platform and avoids a shell
round-trip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Implement platform_compat.ensure_external_binaries (TDD)

**Files:**
- Modify: `zunzun/platform_compat.py`
- Modify: `tests/test_platform_compat.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_platform_compat.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: 2 new tests FAIL.

- [ ] **Step 3: Implement ensure_external_binaries**

Append to `zunzun/platform_compat.py`:
```python
import shutil

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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_platform_compat.py -v`
Expected: all 16 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add zunzun/platform_compat.py tests/test_platform_compat.py
git commit -m "$(cat <<'EOF'
Add platform_compat.ensure_external_binaries

Uses shutil.which() to check for mogrify and gifsicle. Returns the
list of missing binaries so callers can warn or fail. Called from
AppConfig.ready() in a later phase.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Pickle round-trip spike — verify pyeq3 equations survive spawn

**Files:**
- Create: `tests/test_pickle_spike.py`

This task is the empirical verification of the spec §4.4 risk: do pyeq3 equation instances pickle cleanly across a spawn boundary?

- [ ] **Step 1: Write the spike test**

Write `tests/test_pickle_spike.py`:
```python
"""Verify pyeq3 equations and LRP subclasses survive pickle round-trip.

This test is the empirical check for the risk flagged in
docs/superpowers/specs/2026-04-17-cross-platform-design.md §4.4
before Phase 2 rewires LongRunningProcessView to spawn.

We test pickling under the spawn protocol specifically (highest
pickle protocol) because that's what multiprocessing.Process(spawn)
uses internally.
"""
import pickle

import pytest

import pyeq3


def _roundtrip(obj):
    """Pickle with HIGHEST_PROTOCOL (matches multiprocessing.spawn)."""
    data = pickle.dumps(obj, pickle.HIGHEST_PROTOCOL)
    return pickle.loads(data)


def test_pyeq3_polynomial_equation_pickles():
    eq = pyeq3.Models_2D.Polynomial.Polynomial("SSQABS", "Default")
    clone = _roundtrip(eq)
    assert clone.GetDisplayName() == eq.GetDisplayName()
    assert clone.__class__.__name__ == eq.__class__.__name__


def test_pyeq3_spline_equation_pickles():
    eq = pyeq3.Models_2D.Spline.Spline("SSQABS", "Default")
    clone = _roundtrip(eq)
    assert clone.__class__.__name__ == eq.__class__.__name__


def test_pyeq3_user_defined_function_pickles():
    eq = pyeq3.Models_2D.UserDefinedFunction.UserDefinedFunction("SSQABS", "Default")
    # These typically have a parsed function body; ensure the class itself
    # survives even if the parsed state needs re-parsing in the child
    clone = _roundtrip(eq)
    assert clone.__class__.__name__ == eq.__class__.__name__


def test_pyeq3_3d_equation_pickles():
    eq = pyeq3.Models_3D.Polynomial.Polynomial("SSQABS", "Default")
    clone = _roundtrip(eq)
    assert clone.GetDisplayName() == eq.GetDisplayName()


def test_lrp_instance_pickles_minimally():
    """Even the bare LRP instance (no form data yet) should pickle."""
    from zunzun.LongRunningProcess import FitOneEquation
    lrp = FitOneEquation.FitOneEquation()
    clone = _roundtrip(lrp)
    assert clone.__class__.__name__ == "FitOneEquation"
    assert clone.dimensionality == lrp.dimensionality
```

- [ ] **Step 2: Run the spike test**

Run: `uv run pytest tests/test_pickle_spike.py -v`
Expected: all 5 tests PASS.

**If any test fails**, STOP and investigate. The failure would mean the spec §4.4 risk is real and Phase 2's ChildPayload approach needs revision (likely: more aggressive paring of what the payload carries, or custom `__reduce__` methods on specific classes). Document the failure in the commit message and consult the spec author before proceeding with later phases.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pickle_spike.py
git commit -m "$(cat <<'EOF'
Add pickle round-trip spike test for pyeq3 equations

Empirically verifies the spec §4.4 assumption that pyeq3 equations
survive a pickle round-trip at HIGHEST_PROTOCOL (what spawn uses).
All-green here unlocks Phase 2; a failure here would force a spec
revision before rewiring LongRunningProcessView.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Phase 0 verification — full test suite green, manage.py check clean

**Files:** none modified; verification only.

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: all 21 tests PASS (2 smoke + 16 platform_compat + 5 pickle-spike).

- [ ] **Step 2: Run Django system check**

Run: `uv run python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Run Django migrate (idempotent)**

Run: `uv run python manage.py migrate`
Expected: `No migrations to apply.` (session DB already exists from earlier setup.)

- [ ] **Step 4: Phase 0 completion marker**

No commit — Phase 0 is already committed in earlier tasks. Proceed to Phase 1.

---

# Phase 1 — Peripheral shims

Now that `platform_compat` is implemented and tested, migrate every call site that uses `os.getloadavg`, `/proc`, `vmstat`, `os.popen`, or `psutil.STATUS_ZOMBIE` to the new module. The fork-based concurrency architecture is **not** touched in this phase — only the peripheral OS calls. After Phase 1 the site still uses `os.fork()`, but every other platform-specific call has been abstracted.

## Task 12: Migrate os.getloadavg in zunzun/views.py

**Files:**
- Modify: `zunzun/views.py` (lines 216, 543)

- [ ] **Step 1: Update views.py imports**

Find the existing imports block at the top of `zunzun/views.py` (starts around line 1). Add after the existing `from . import LongRunningProcess` line:

```python
from . import platform_compat
```

- [ ] **Step 2: Replace os.getloadavg in StatusView (line 216)**

In `zunzun/views.py`, find the line:
```python
    loadavg = os.getloadavg()
```
inside the `StatusView` function. Change to:
```python
    loadavg = platform_compat.get_loadavg()
```

- [ ] **Step 3: Replace os.getloadavg in HomePageView (line 543)**

Find the line:
```python
    items_to_render['loadavg'] = os.getloadavg()
```
inside the `HomePageView` function. Change to:
```python
    items_to_render['loadavg'] = platform_compat.get_loadavg()
```

- [ ] **Step 4: Verify Django still loads**

Run: `uv run python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit**

```bash
git add zunzun/views.py
git commit -m "$(cat <<'EOF'
Migrate os.getloadavg calls in views.py to platform_compat

Two call sites (StatusView, HomePageView). Behavior identical on
Linux (psutil.getloadavg wraps os.getloadavg); newly functional on
Windows via psutil's simulated load average.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Migrate GetParallelProcessCount and os.getloadavg in StatusMonitoredLongRunningProcessPage

**Files:**
- Modify: `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py` (lines 165-196, 822)

- [ ] **Step 1: Add platform_compat import**

At the top of `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py`, after the existing `from . import DataObject` line, add:

```python
from zunzun import platform_compat
```

- [ ] **Step 2: Replace GetParallelProcessCount method (lines 165-196)**

Replace the entire body of `GetParallelProcessCount(self)` method — from the line `pid_trace.pid_trace()` (first line of method body) through the final `return ppCount` — with:

```python
    def GetParallelProcessCount(self):
        pid_trace.pid_trace()
        ppCount = platform_compat.get_parallel_process_count()
        pid_trace.pid_trace()
        return ppCount
```

This collapses the /proc/loadavg read and vmstat parse into a single delegation.

- [ ] **Step 3: Replace os.getloadavg in the same file (line 822)**

Find:
```python
        itemsToRender['loadavg'] = os.getloadavg()
```
Change to:
```python
        itemsToRender['loadavg'] = platform_compat.get_loadavg()
```

- [ ] **Step 4: Verify**

Run: `uv run python manage.py check`
Run: `uv run pytest tests/ -v`
Expected: both clean, no regressions.

- [ ] **Step 5: Commit**

```bash
git add zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py
git commit -m "$(cat <<'EOF'
Migrate GetParallelProcessCount and getloadavg to platform_compat

Eliminates the /proc/loadavg read and the vmstat subprocess parse
in favor of platform_compat.get_parallel_process_count (psutil-backed).
Also migrates the remaining os.getloadavg call site.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Migrate os.popen('mogrify') calls in ReportsAndGraphs.py

**Files:**
- Modify: `zunzun/LongRunningProcess/ReportsAndGraphs.py` (lines 1513, 1575)

- [ ] **Step 1: Add platform_compat import**

At the top of `zunzun/LongRunningProcess/ReportsAndGraphs.py`, find the existing imports block and add:

```python
from zunzun import platform_compat
```

- [ ] **Step 2: Replace os.popen('mogrify') at line 1513**

Find:
```python
                p = os.popen('mogrify -format gif ' + frameName)
```

Replace with:
```python
                platform_compat.run_tool('mogrify', ['-format', 'gif', frameName])
```

Also remove the subsequent `p.close()` or `p.read()` line if present immediately after (the original os.popen use may not have needed close; verify by reading 2 lines of context after the replacement).

- [ ] **Step 3: Replace os.popen('mogrify') at line 1575**

Find:
```python
                p = os.popen('mogrify -format gif ' + frameName)
```
(the second occurrence in the file)

Replace with:
```python
                platform_compat.run_tool('mogrify', ['-format', 'gif', frameName])
```

Same note about removing any `p.close()` if present.

- [ ] **Step 4: Verify Django check**

Run: `uv run python manage.py check`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add zunzun/LongRunningProcess/ReportsAndGraphs.py
git commit -m "$(cat <<'EOF'
Migrate os.popen('mogrify') to platform_compat.run_tool

Two call sites in ReportsAndGraphs.py. Uses subprocess with an
argument list (no shell=True), eliminating a pre-existing shell
injection surface from the string-concatenated filename.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Migrate os.popen('gifsicle') calls in ReportsAndGraphs.py

**Files:**
- Modify: `zunzun/LongRunningProcess/ReportsAndGraphs.py` (lines 1517, 1579)

- [ ] **Step 1: Replace os.popen('gifsicle') at line 1517**

Find:
```python
            p = os.popen('gifsicle --colors 256 --loopcount  ' + self.physicalFileLocation[:-4] + '__*gif > ' + self.physicalFileLocation)
```

This has TWO things to fix: glob expansion (`__*gif` was shell-expanded) and stdout redirection (`>`). Replace with:

```python
            import glob as _glob
            _frames = sorted(_glob.glob(self.physicalFileLocation[:-4] + '__*gif'))
            platform_compat.run_tool(
                'gifsicle',
                ['--colors', '256', '--loopcount', *_frames],
                stdout_file=self.physicalFileLocation,
            )
```

Remove any subsequent `p.close()` or `p.read()` on the next line.

- [ ] **Step 2: Replace os.popen('gifsicle') at line 1579**

Apply the identical replacement pattern from Step 1 to the second occurrence. The shell-glob and stdout-redirect handling is the same.

- [ ] **Step 3: Verify Django check**

Run: `uv run python manage.py check`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add zunzun/LongRunningProcess/ReportsAndGraphs.py
git commit -m "$(cat <<'EOF'
Migrate os.popen('gifsicle') to platform_compat.run_tool

Two call sites. Handles both the shell-glob '__*gif' expansion
(now via glob.glob) and the stdout '> outfile' redirection (now
via run_tool's stdout_file parameter).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Migrate os.popen('rm') calls in ReportsAndGraphs.py

**Files:**
- Modify: `zunzun/LongRunningProcess/ReportsAndGraphs.py` (lines 1519, 1581)

- [ ] **Step 1: Replace os.popen('rm') at line 1519**

Find:
```python
            p = os.popen('rm ' + self.physicalFileLocation[:-4] + '__*')
```

Replace with:
```python
            platform_compat.remove_files_matching(self.physicalFileLocation[:-4] + '__*')
```

Remove any subsequent `p.close()` / `p.read()`.

- [ ] **Step 2: Replace os.popen('rm') at line 1581**

Apply identical replacement to the second occurrence.

- [ ] **Step 3: Verify**

Run: `uv run python manage.py check`
Run: `uv run pytest tests/ -v`
Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add zunzun/LongRunningProcess/ReportsAndGraphs.py
git commit -m "$(cat <<'EOF'
Migrate os.popen('rm') to platform_compat.remove_files_matching

Two call sites in ReportsAndGraphs.py. POSIX-only 'rm' command
replaced with glob.glob + os.remove. Also the last os.popen()
site in the codebase.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: Migrate psutil.STATUS_ZOMBIE reap in CommonToAllViews

**Files:**
- Modify: `zunzun/views.py` (lines ~675-685)

- [ ] **Step 1: Replace the zombie-reap loop**

Find the block in `CommonToAllViews` function (starts around line 675):
```python
    # if possible, kill any child zombie processes
    # based on # from https://psutil.readthedocs.io/en/latest/#recipes
    child_procs = psutil.Process().children()
    for child in child_procs:
        if child.status() == psutil.STATUS_ZOMBIE:
            child.wait() # should return immediately for zombie processes
```

Replace with:
```python
    # Reap any completed multiprocessing children so they don't linger.
    # No-op on Windows (no zombies), proper cleanup on Unix.
    platform_compat.reap_completed_children()
```

- [ ] **Step 2: Verify**

Run: `uv run python manage.py check`
Run: `uv run pytest tests/ -v`
Expected: both clean.

- [ ] **Step 3: Commit**

```bash
git add zunzun/views.py
git commit -m "$(cat <<'EOF'
Migrate zombie-reap loop to platform_compat.reap_completed_children

Replaces the psutil.STATUS_ZOMBIE sweep with a cross-platform
multiprocessing.active_children() + join(timeout=0) pattern.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: Phase 1 verification — full regression

**Files:** none modified; verification only.

- [ ] **Step 1: Confirm no os.popen / /proc / vmstat / STATUS_ZOMBIE calls remain in the migrated surface**

Run:
```bash
grep -rn "os\.popen\|STATUS_ZOMBIE\|/proc/loadavg\|os\.getloadavg\|vmstat" zunzun/ --include="*.py"
```

Expected: only matches should be inside `zunzun/platform_compat.py` itself (which uses `psutil.getloadavg` internally — that's fine). If any match appears outside `platform_compat.py`, a migration site was missed; return to the relevant task.

- [ ] **Step 2: Full test run + Django check**

Run: `uv run pytest tests/ -v && uv run python manage.py check`
Expected: both clean.

- [ ] **Step 3: End-to-end Linux smoke (if on Linux/WSL)**

If running on Linux (native or WSL), start the dev server and submit a fit manually to sanity-check:

```bash
uv run python manage.py runserver 127.0.0.1:8000 &
sleep 3
curl -s http://127.0.0.1:8000/ | grep -q "ZunZunSite3"
```

Expected: grep finds the title. Kill the server with `kill %1` or Ctrl+C.

Note: this works on Linux/WSL only. On native Windows this will still fail because `os.fork()` is still used — that's Phase 2's fix.

- [ ] **Step 4: Phase 1 completion marker**

No commit — Phase 1 is complete via the per-task commits. Proceed to Phase 2.

---

# Phase 2 — ChildPayload + spawn (RISKY)

This is the architectural shift. `os.fork()` in `LongRunningProcessView` becomes `multiprocessing.Process` with the `spawn` start method. The picklability boundary is enforced via a new `ChildPayload` dataclass that carries only what `PerformAllWork()` needs.

**Pre-flight:** Task 10's pickle spike MUST have all tests green. If any failed, the design needs revision before this phase.

## Task 19: Create ChildPayload dataclass and _run_fit_child entrypoint

**Files:**
- Create: `zunzun/LongRunningProcess/child_payload.py`
- Create: `tests/test_child_payload.py`

- [ ] **Step 1: Write failing tests for ChildPayload**

Write `tests/test_child_payload.py`:
```python
"""Tests for the spawn-safe ChildPayload dataclass."""
import pickle


def test_child_payload_round_trips():
    from zunzun.LongRunningProcess.child_payload import ChildPayload
    p = ChildPayload(
        lrp_class_path="zunzun.LongRunningProcess.FitOneEquation.FitOneEquation",
        session_key_status="s1",
        session_key_data="s2",
        session_key_functionfinder="s3",
        dimensionality=2,
        renice_level=10,
        data_object=None,
        equation=None,
        extra={"foo": "bar"},
    )
    clone = pickle.loads(pickle.dumps(p, pickle.HIGHEST_PROTOCOL))
    assert clone.lrp_class_path == p.lrp_class_path
    assert clone.dimensionality == 2
    assert clone.extra == {"foo": "bar"}


def test_child_payload_has_required_fields():
    """Ensure the dataclass exposes every field needed by PerformAllWork."""
    from zunzun.LongRunningProcess.child_payload import ChildPayload
    import dataclasses
    fields = {f.name for f in dataclasses.fields(ChildPayload)}
    assert fields == {
        "lrp_class_path",
        "session_key_status",
        "session_key_data",
        "session_key_functionfinder",
        "dimensionality",
        "renice_level",
        "data_object",
        "equation",
        "extra",
    }
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_child_payload.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create child_payload.py**

Write `zunzun/LongRunningProcess/child_payload.py`:
```python
"""Spawn-safe payload for multiprocessing.Process handoff.

The LongRunningProcessView used to call os.fork() which inherited the
parent's full memory, including non-picklable objects like the bound
Django Form. multiprocessing.Process(spawn) requires everything passed
to the child to be picklable. ChildPayload carries only the primitives
and pickle-safe objects the child needs to reconstruct an LRP instance
and run PerformAllWork().
"""
from __future__ import annotations

import importlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass
class ChildPayload:
    """Picklable snapshot of the state PerformAllWork() needs.

    lrp_class_path: dotted module path, e.g.
      "zunzun.LongRunningProcess.FitOneEquation.FitOneEquation".
      The child uses importlib + getattr to resurrect the LRP class,
      then hydrates fields from this payload.
    session_key_*: Django SessionStore keys (strings).
    dimensionality: 1, 2, or 3.
    renice_level: Unix nice value to apply via platform_compat.
    data_object: the existing DataObject attr-bag; already picklable.
    equation: pyeq3 equation instance (picklability verified in
      tests/test_pickle_spike.py).
    extra: subclass-specific fields. Each Fit* subclass extends this
      dict with its flags (spline order, polynomial flags, etc.).
    """

    lrp_class_path: str
    session_key_status: str
    session_key_data: str
    session_key_functionfinder: str
    dimensionality: int
    renice_level: int
    data_object: Any
    equation: Any
    extra: dict[str, Any] = field(default_factory=dict)


def _run_fit_child(payload: ChildPayload) -> None:
    """Entrypoint function for multiprocessing.Process(target=...).

    Executes in the spawned child process. Reconstructs an LRP
    instance from the payload, runs PerformAllWork(), then returns.

    Any uncaught exception is logged to temp/{pid}.log (matching the
    existing logging pattern in views.LongRunningProcessView) before
    the child exits.
    """
    from zunzun import platform_compat

    # Apply nice level to the child process itself
    try:
        platform_compat.set_process_niceness(os.getpid(), payload.renice_level)
    except Exception as e:  # noqa: BLE001 — defensive; niceness is best-effort
        _logger.info("Child process could not renice: %s", e)

    # Resolve the LRP class
    module_path, _, class_name = payload.lrp_class_path.rpartition(".")
    module = importlib.import_module(module_path)
    lrp_class = getattr(module, class_name)

    # Reconstruct the LRP. The subclass is responsible for populating
    # itself from the payload via apply_child_payload().
    lrp = lrp_class()
    lrp.apply_child_payload(payload)

    try:
        lrp.PerformAllWork()
    except Exception:
        import settings
        import logging as _logging
        log_path = os.path.join(settings.TEMP_FILES_DIR, f"{os.getpid()}.log")
        _logging.basicConfig(filename=log_path, level=_logging.DEBUG)
        _logging.exception("Child exception in _run_fit_child")

        try:
            lrp.SaveDictionaryOfItemsToSessionStore(
                "status",
                {"currentStatus":
                    "An unknown exception has occurred, and an email with "
                    "details has been sent to the site administrator."}
            )
        except Exception:
            _logging.exception("Also failed to write status after child exception")
    finally:
        time.sleep(1.0)  # match the existing post-work sleep
        # Child returns (implicit); multiprocessing handles exit code.
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_child_payload.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add zunzun/LongRunningProcess/child_payload.py tests/test_child_payload.py
git commit -m "$(cat <<'EOF'
Add ChildPayload dataclass and _run_fit_child entrypoint

Introduces the spawn-safe boundary for the long-running-fit child
process. ChildPayload carries only picklable fields; _run_fit_child
is the top-level function multiprocessing.Process targets, which
reconstructs an LRP instance and runs PerformAllWork().

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 20: Add default build_child_payload and apply_child_payload on StatusMonitoredLongRunningProcessPage

**Files:**
- Modify: `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py`

- [ ] **Step 1: Add imports at top of file**

After the existing `from zunzun import platform_compat` line added in Task 13, add:

```python
from .child_payload import ChildPayload
```

- [ ] **Step 2: Add build_child_payload method (default implementation)**

Inside the `StatusMonitoredLongRunningProcessPage` class body, after the `__init__` method and before `PerformWorkInParallel`, add:

```python
    def build_child_payload(self) -> ChildPayload:
        """Produce a picklable snapshot for the spawned child process.

        Default implementation covers the common subset (session keys,
        dimensionality, renice level, dataObject). Subclasses override
        to add fit-specific fields via the `extra` dict.
        """
        return ChildPayload(
            lrp_class_path=f"{self.__class__.__module__}.{self.__class__.__name__}",
            session_key_status=self.session_key_status,
            session_key_data=self.session_key_data,
            session_key_functionfinder=getattr(self, "session_key_functionfinder", ""),
            dimensionality=self.dimensionality,
            renice_level=self.reniceLevel,
            data_object=getattr(self, "dataObject", None),
            equation=None,  # overridden by fit subclasses
            extra={},
        )

    def apply_child_payload(self, payload: ChildPayload) -> None:
        """Re-hydrate this instance (in the child process) from the payload.

        Default implementation restores the common fields. Subclasses
        override to populate fit-specific state from payload.extra.
        """
        self.session_key_status = payload.session_key_status
        self.session_key_data = payload.session_key_data
        self.session_key_functionfinder = payload.session_key_functionfinder
        self.dimensionality = payload.dimensionality
        self.reniceLevel = payload.renice_level
        self.dataObject = payload.data_object
```

- [ ] **Step 3: Verify**

Run: `uv run python manage.py check`
Run: `uv run pytest tests/ -v`
Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py
git commit -m "$(cat <<'EOF'
Add default build_child_payload/apply_child_payload on base LRP class

Establishes the contract subclasses override to extend. Base
implementation handles the common fields shared across every
LRP subclass (session keys, dimensionality, renice, dataObject).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 21: Override build_child_payload/apply_child_payload on FittingBaseClass

**Files:**
- Modify: `zunzun/LongRunningProcess/FittingBaseClass.py`

- [ ] **Step 1: Add import**

At the top of `zunzun/LongRunningProcess/FittingBaseClass.py`, add:
```python
from .child_payload import ChildPayload
```

- [ ] **Step 2: Add build_child_payload override**

Inside the `FittingBaseClass` class body, add:

```python
    def build_child_payload(self):
        payload = super().build_child_payload()
        # Fit subclasses always have a bound equation via boundForm
        if self.boundForm is not None:
            payload.equation = self.boundForm.equation
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        # In the child, there is no request and no boundForm — the
        # equation comes directly from the payload.
        self.equationFromPayload = payload.equation
```

- [ ] **Step 3: Verify**

Run: `uv run python manage.py check`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add zunzun/LongRunningProcess/FittingBaseClass.py
git commit -m "$(cat <<'EOF'
Override build_child_payload/apply_child_payload on FittingBaseClass

Adds the pyeq3 equation instance to the payload (all fit subclasses
need it). The child reconstructs it from payload.equation rather
than via boundForm.equation (boundForm isn't picklable).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 22: Override build_child_payload on the seven concrete Fit* subclasses

**Files:**
- Modify each of:
  - `zunzun/LongRunningProcess/FitSpline.py`
  - `zunzun/LongRunningProcess/FitUserDefinedFunction.py`
  - `zunzun/LongRunningProcess/FitUserCustomizablePolynomial.py`
  - `zunzun/LongRunningProcess/FitUserSelectablePolynomial.py`
  - `zunzun/LongRunningProcess/FitUserSelectablePolyfunctional.py`
  - `zunzun/LongRunningProcess/FitUserSelectableRational.py`
  - `zunzun/LongRunningProcess/FitOneEquation.py` (may need nothing beyond the FittingBaseClass default — verify)

Each subclass carries subclass-specific form fields that the child needs. These go into `payload.extra` as a dict of primitives.

For each file, add the two methods below inside the subclass body, using the specific field table beneath.

### Table: per-subclass `extra` fields

Read the existing `TransferFormDataToDataObject` in each file to see which attributes get set on `self.dataObject` from form fields. The general rule: any attribute that `PerformAllWork` reads on the equation or dataObject that isn't already in the base payload needs to be in `extra`.

| Subclass | Fields to include in `extra` |
|---|---|
| `FitOneEquation` | None needed — base FittingBaseClass payload is sufficient |
| `FitSpline` | `splineSmoothness: float`, `splineOrderX: int`, `splineOrderY: int` (3D only) |
| `FitUserDefinedFunction` | `userDefinedFunctionText: str` |
| `FitUserCustomizablePolynomial` | `polynomial2DFlags: list` |
| `FitUserSelectablePolynomial` | `xPolynomialOrder: int`, `yPolynomialOrder: int` (3D only) |
| `FitUserSelectablePolyfunctional` | `polyfunctional2DFlags: list`, `polyfunctional3DFlags: list` |
| `FitUserSelectableRational` | `rationalNumeratorFlags: list`, `rationalDenominatorFlags: list` |

- [ ] **Step 1: Add override in FitSpline.py**

In `zunzun/LongRunningProcess/FitSpline.py`, add the import (if not present):
```python
from .child_payload import ChildPayload
```

Add inside the `FitSpline` class body:
```python
    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["splineSmoothness"] = self.dataObject.splineSmoothness
        payload.extra["splineOrderX"] = self.dataObject.splineOrderX
        if self.dimensionality == 3:
            payload.extra["splineOrderY"] = self.dataObject.splineOrderY
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.dataObject.splineSmoothness = payload.extra["splineSmoothness"]
        self.dataObject.splineOrderX = payload.extra["splineOrderX"]
        if self.dimensionality == 3:
            self.dataObject.splineOrderY = payload.extra["splineOrderY"]
```

- [ ] **Step 2: Add override in FitUserDefinedFunction.py**

In `zunzun/LongRunningProcess/FitUserDefinedFunction.py`:
```python
from .child_payload import ChildPayload


class FitUserDefinedFunction(...):  # existing class
    # ... existing methods ...

    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["userDefinedFunctionText"] = self.dataObject.userDefinedFunctionText
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.dataObject.userDefinedFunctionText = payload.extra["userDefinedFunctionText"]
```

- [ ] **Step 3: Add override in FitUserCustomizablePolynomial.py**

```python
from .child_payload import ChildPayload


class FitUserCustomizablePolynomial(...):
    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["polynomial2DFlags"] = self.dataObject.polynomial2DFlags
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.dataObject.polynomial2DFlags = payload.extra["polynomial2DFlags"]
```

- [ ] **Step 4: Add override in FitUserSelectablePolynomial.py**

```python
from .child_payload import ChildPayload


class FitUserSelectablePolynomial(...):
    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["xPolynomialOrder"] = self.dataObject.xPolynomialOrder
        if self.dimensionality == 3:
            payload.extra["yPolynomialOrder"] = self.dataObject.yPolynomialOrder
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.dataObject.xPolynomialOrder = payload.extra["xPolynomialOrder"]
        if self.dimensionality == 3:
            self.dataObject.yPolynomialOrder = payload.extra["yPolynomialOrder"]
```

- [ ] **Step 5: Add override in FitUserSelectablePolyfunctional.py**

```python
from .child_payload import ChildPayload


class FitUserSelectablePolyfunctional(...):
    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["polyfunctional2DFlags"] = self.dataObject.polyfunctional2DFlags
        payload.extra["polyfunctional3DFlags"] = self.dataObject.polyfunctional3DFlags
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.dataObject.polyfunctional2DFlags = payload.extra["polyfunctional2DFlags"]
        self.dataObject.polyfunctional3DFlags = payload.extra["polyfunctional3DFlags"]
```

- [ ] **Step 6: Add override in FitUserSelectableRational.py**

```python
from .child_payload import ChildPayload


class FitUserSelectableRational(...):
    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["rationalNumeratorFlags"] = self.dataObject.rationalNumeratorFlags
        payload.extra["rationalDenominatorFlags"] = self.dataObject.rationalDenominatorFlags
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.dataObject.rationalNumeratorFlags = payload.extra["rationalNumeratorFlags"]
        self.dataObject.rationalDenominatorFlags = payload.extra["rationalDenominatorFlags"]
```

- [ ] **Step 7: Verify FitOneEquation needs no override**

Read `zunzun/LongRunningProcess/FitOneEquation.py`. If its `PerformAllWork` uses only fields covered by the `FittingBaseClass` payload (i.e. just `self.boundForm.equation`), no override needed. If it uses additional fields, add an override following the same pattern as Step 1.

- [ ] **Step 8: Verify Django loads**

Run: `uv run python manage.py check`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add zunzun/LongRunningProcess/Fit*.py
git commit -m "$(cat <<'EOF'
Override build_child_payload on every Fit* subclass

Each concrete Fit subclass now extends the payload's `extra` dict
with its subclass-specific flags (spline order, polynomial flags,
rational num/den flags, UDF text). apply_child_payload re-hydrates
the same fields inside the child process.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 23: Override build_child_payload on FunctionFinder and FunctionFinderResults

**Files:**
- Modify: `zunzun/LongRunningProcess/FunctionFinder.py`
- Modify: `zunzun/LongRunningProcess/FunctionFinderResults.py`

Function finders have their own config state (rank, equation-family-inclusion flags) that the child needs.

- [ ] **Step 1: Read FunctionFinder.py's TransferFormDataToDataObject**

Open `zunzun/LongRunningProcess/FunctionFinder.py` and locate `TransferFormDataToDataObject` (search for the method name). List every attribute assigned to `self.dataObject` from the form. Typical fields include `fittingTarget`, `smoothnessControl`, `smoothnessExactOrMax`, `extendedEquationTypes`, `equationFamilyInclusion`, `logLinX/Y/Z`.

- [ ] **Step 2: Add override in FunctionFinder.py**

Add to the `FunctionFinder` class body:
```python
    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["fittingTarget"] = self.dataObject.fittingTarget
        payload.extra["smoothnessControl"] = self.dataObject.smoothnessControl
        payload.extra["smoothnessExactOrMax"] = self.dataObject.smoothnessExactOrMax
        payload.extra["extendedEquationTypes"] = self.dataObject.extendedEquationTypes
        payload.extra["equationFamilyInclusion"] = self.dataObject.equationFamilyInclusion
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.dataObject.fittingTarget = payload.extra["fittingTarget"]
        self.dataObject.smoothnessControl = payload.extra["smoothnessControl"]
        self.dataObject.smoothnessExactOrMax = payload.extra["smoothnessExactOrMax"]
        self.dataObject.extendedEquationTypes = payload.extra["extendedEquationTypes"]
        self.dataObject.equationFamilyInclusion = payload.extra["equationFamilyInclusion"]
```

- [ ] **Step 3: Add override in FunctionFinderResults.py**

`FunctionFinderResults` has a `rank` attribute that views.py's dispatcher sets directly (not from the form). Add:
```python
    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["rank"] = self.rank
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.rank = payload.extra["rank"]
```

- [ ] **Step 4: Verify**

Run: `uv run python manage.py check`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add zunzun/LongRunningProcess/FunctionFinder.py zunzun/LongRunningProcess/FunctionFinderResults.py
git commit -m "$(cat <<'EOF'
Override build_child_payload on FunctionFinder(Results)

FunctionFinder carries fit-target + smoothness + family-inclusion
flags in its payload. FunctionFinderResults carries the rank.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 24: Override build_child_payload on CharacterizeData and StatisticalDistributions

**Files:**
- Modify: `zunzun/LongRunningProcess/CharacterizeData.py`
- Modify: `zunzun/LongRunningProcess/StatisticalDistributions.py`

These inherit directly from `StatusMonitoredLongRunningProcessPage`, not from `FittingBaseClass`, so they do not have `self.boundForm.equation`.

- [ ] **Step 1: Verify CharacterizeData needs no override**

Read `zunzun/LongRunningProcess/CharacterizeData.py` `TransferFormDataToDataObject`. If all the fields it uses live on `self.dataObject` (already in base payload), no override is needed — the base `StatusMonitoredLongRunningProcessPage.build_child_payload()` default handles it.

- [ ] **Step 2: Verify StatisticalDistributions needs no override**

Same process for `zunzun/LongRunningProcess/StatisticalDistributions.py`. If it stores its config entirely on `self.dataObject`, the base default is sufficient.

- [ ] **Step 3: If either needs custom fields**

If either subclass stores state outside `self.dataObject` (e.g., directly on `self`), add a `build_child_payload` override that copies those fields into `payload.extra`, following the pattern from Tasks 22–23.

- [ ] **Step 4: Verify**

Run: `uv run python manage.py check`
Expected: clean.

- [ ] **Step 5: Commit (only if changes were made)**

If no changes were needed, skip this commit. Otherwise:
```bash
git add zunzun/LongRunningProcess/CharacterizeData.py zunzun/LongRunningProcess/StatisticalDistributions.py
git commit -m "$(cat <<'EOF'
Override build_child_payload on CharacterizeData / StatisticalDistributions

Adds subclass-specific fields to the child payload extra dict.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 25: Extend pickle round-trip tests to cover every Fit* subclass's payload

**Files:**
- Modify: `tests/test_pickle_spike.py`

- [ ] **Step 1: Add per-subclass payload round-trip tests**

Append to `tests/test_pickle_spike.py`:
```python
def test_fit_one_equation_payload_round_trips():
    from zunzun.LongRunningProcess.FitOneEquation import FitOneEquation
    lrp = FitOneEquation()
    lrp.session_key_status = "k1"
    lrp.session_key_data = "k2"
    lrp.session_key_functionfinder = "k3"
    lrp.dimensionality = 2
    lrp.reniceLevel = 10
    lrp.dataObject = None
    payload = lrp.build_child_payload()
    clone = pickle.loads(pickle.dumps(payload, pickle.HIGHEST_PROTOCOL))
    assert clone.lrp_class_path.endswith("FitOneEquation")
    assert clone.session_key_status == "k1"


def test_fit_spline_payload_round_trips():
    from zunzun.LongRunningProcess.FitSpline import FitSpline

    class FakeDO:
        splineSmoothness = 1.0
        splineOrderX = 3
        splineOrderY = 3

    lrp = FitSpline()
    lrp.session_key_status = "k1"
    lrp.session_key_data = "k2"
    lrp.session_key_functionfinder = "k3"
    lrp.dimensionality = 2
    lrp.reniceLevel = 10
    lrp.dataObject = FakeDO()
    lrp.boundForm = None
    payload = lrp.build_child_payload()
    clone = pickle.loads(pickle.dumps(payload, pickle.HIGHEST_PROTOCOL))
    assert clone.extra["splineOrderX"] == 3


def test_characterize_data_payload_round_trips():
    from zunzun.LongRunningProcess.CharacterizeData import CharacterizeData

    class FakeDO:
        pass

    lrp = CharacterizeData()
    lrp.session_key_status = "k1"
    lrp.session_key_data = "k2"
    lrp.session_key_functionfinder = "k3"
    lrp.dimensionality = 1
    lrp.reniceLevel = 10
    lrp.dataObject = FakeDO()
    payload = lrp.build_child_payload()
    clone = pickle.loads(pickle.dumps(payload, pickle.HIGHEST_PROTOCOL))
    assert clone.lrp_class_path.endswith("CharacterizeData")
```

Add analogous tests for each remaining LRP subclass (`FitUserDefinedFunction`, `FitUserCustomizablePolynomial`, `FitUserSelectablePolynomial`, `FitUserSelectablePolyfunctional`, `FitUserSelectableRational`, `FunctionFinder`, `FunctionFinderResults`, `StatisticalDistributions`). Each follows the same pattern: instantiate, populate required attrs with fake values, build_child_payload, round-trip, assert on the subclass-specific `extra` fields.

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_pickle_spike.py -v`
Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pickle_spike.py
git commit -m "$(cat <<'EOF'
Add payload round-trip tests for every LRP subclass

Empirically verifies that build_child_payload output pickles cleanly
under HIGHEST_PROTOCOL (spawn protocol) for every concrete LRP. This
is the gate before rewiring LongRunningProcessView to use Process.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 26: Replace os.fork() in LongRunningProcessView with multiprocessing.Process(spawn)

**Files:**
- Modify: `zunzun/views.py` (around lines 417-447)

This is the core architectural change.

- [ ] **Step 1: Add multiprocessing import**

At the top of `zunzun/views.py`, find the existing `import numpy, multiprocessing` line (around line 19). It already imports multiprocessing — no change needed. If the import is absent, add it.

Also add at the top of the imports block:
```python
from .LongRunningProcess.child_payload import _run_fit_child
```

- [ ] **Step 2: Replace the fork block in LongRunningProcessView**

Find this block (around line 417):
```python
    processID_1 = os.fork()
    if processID_1 == 0: # child process, kill when done

        os.nice(LRP.reniceLevel)

        # if top-level exception save data for debugging
        dataObjectString = ''
        #try:
        #    dataObjectString = str(LRP.dataObject)
        #except:
        #    dataObjectString = 'could not str(LRP.dataObject)'

        try:
            LRP.PerformAllWork()
        except:
            import logging
            logging.basicConfig(filename = os.path.join(settings.TEMP_FILES_DIR,  str(os.getpid()) + '.log'),level=logging.DEBUG)

            logging.exception('Site top-level exception\n' + dataObjectString + '\n')

            extraInfo = '\n\nrequest.META info:\n'
            for item in request.META:
                extraInfo += str(item) + ' : ' + str(request.META[item]) + '\n'

            LRP.SaveDictionaryOfItemsToSessionStore('status', {'currentStatus':"An unknown exception has occurred, and an email with details has been sent to the site administrator. These are sometimes caused by taking the exponent of large numbers."})
        finally:
            time.sleep(1.0)
            #if LRP.pool:
            #    LRP.pool.close()
            #    LRP.pool.join()
            os._exit(0) # kill this child process

    # using HTTP_HOST allows dev server
    return HttpResponseRedirect('http://' + request.META['HTTP_HOST'] + '/StatusAndResults/')
```

Replace with:
```python
    # Build the picklable payload in the parent, then hand it to a spawned
    # child process. Spawn (vs fork) is mandatory on Windows and safer on
    # Linux under a multi-threaded WSGI server like Waitress.
    payload = LRP.build_child_payload()

    # Close DB connections before spawning — otherwise the fresh Python
    # interpreter in the child can race on stale connection state. This
    # mirrors the prior-art pattern at the HomePageView fork.
    db.connections.close_all()
    close_old_connections()

    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=_run_fit_child, args=(payload,), daemon=False)
    child.start()

    return HttpResponseRedirect('http://' + request.META['HTTP_HOST'] + '/StatusAndResults/')
```

Remove the now-obsolete `os.fork()` / `os._exit()` / `os.nice()` code that was in the original block.

- [ ] **Step 3: Verify**

Run: `uv run python manage.py check`
Run: `uv run pytest tests/ -v`
Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add zunzun/views.py
git commit -m "$(cat <<'EOF'
Replace os.fork() in LongRunningProcessView with Process(spawn)

The architectural heart of the cross-platform migration. Parent now
builds a picklable ChildPayload and spawns a multiprocessing.Process
with the spawn start method (Windows-mandatory, safe under any WSGI
server). The child runs _run_fit_child from child_payload.py which
re-hydrates the LRP instance and calls PerformAllWork().

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 27: Remove obsolete os._exit calls in StatusMonitoredLongRunningProcessPage

**Files:**
- Modify: `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py` (lines 672, 689)

With the multiprocessing.Process lifecycle, `os._exit(0)` is no longer needed — returning from `_run_fit_child` cleans up correctly.

- [ ] **Step 1: Remove os._exit at line 672**

Find:
```python
            os._exit(0) # kills pool processes
```
Delete this line. Verify the surrounding context: if the line is inside a `finally:` block that no longer has any statements, replace the block with a comment `# no-op after spawn migration` so the try/except remains syntactically valid.

- [ ] **Step 2: Remove os._exit at line 689**

Same treatment.

- [ ] **Step 3: Verify**

Run: `uv run python manage.py check`
Run: `uv run pytest tests/ -v`
Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py
git commit -m "$(cat <<'EOF'
Remove obsolete os._exit calls after spawn migration

multiprocessing.Process cleans up child processes on return;
os._exit was the Unix-fork idiom and is no longer appropriate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 28: Write scripts/smoke_test.py

**Files:**
- Create: `scripts/smoke_test.py`
- Create: `scripts/__init__.py` (empty, so Python sees scripts/ as a package if needed)

- [ ] **Step 1: Create scripts/__init__.py (empty)**

Write empty file: `scripts/__init__.py`

- [ ] **Step 2: Create scripts/smoke_test.py**

Write `scripts/smoke_test.py`:
```python
"""Cross-platform end-to-end smoke test for zunzunsite3.

Starts a Waitress subprocess on a free port, POSTs a 2D polynomial-
quadratic fit against the default sample data, polls /StatusAndResults/
until the fit completes, asserts on known numeric coefficients, then
stops the server. Exits 0 on success, nonzero on failure.

Reference coefficients (from funkload_tests/test_Simple.py — preserved
here because FunkLoad no longer runs):
  Minimum: -5.824100E-02, -5.610455E-02
  Maximum:  7.692989E-02,  1.154094E-02

Usage:
  uv run python scripts/smoke_test.py
"""
import contextlib
import socket
import subprocess
import sys
import time

import requests


def _find_free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Sample data lifted from funkload_tests/test_Simple.py default_data2D
_DATA_2D = """X Y
5.357 3.76
5.684 6.1
6.097 4.94
6.241 7.104
6.697 2.054
7.061 1.65
7.457 0.412
8.236 2.016
8.531 3.8
9.861 1.95
"""

_FORM_FIELDS = {
    "commaConversion": "I",
    "graphSize": "320x240",
    "animationSize": "0x0",
    "scientificNotationX": "AUTO",
    "scientificNotationY": "AUTO",
    "dataNameX": "X Data",
    "dataNameY": "Y Data",
    "graphScaleRadioButtonX": "0.050",
    "graphScaleRadioButtonY": "0.050",
    "logLinX": "LIN",
    "logLinY": "LIN",
    "logLinZ": "LIN",
    "fittingTarget": "SSQABS",
    "textDataEditor": _DATA_2D,
}

_EXPECTED_STRINGS = [
    "-5.824100E-02",
    "-5.610455E-02",
]


def run_smoke() -> int:
    port = _find_free_port()
    base = f"http://127.0.0.1:{port}"
    # Use the installed waitress-serve console script. On uv-managed envs
    # it's on PATH when the script is invoked via `uv run`. No sys.executable
    # wrapper because `python -m waitress` is not a standard entry point.
    proc = subprocess.Popen(
        [
            "waitress-serve",
            f"--listen=127.0.0.1:{port}",
            "wsgi:application",
        ]
    )
    try:
        # Wait for server to be ready
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                requests.get(base + "/", timeout=1)
                break
            except requests.ConnectionError:
                time.sleep(0.5)
        else:
            print("ERROR: server never became ready", file=sys.stderr)
            return 1

        # Get homepage to establish session cookie
        session = requests.Session()
        session.get(base + "/")

        # POST the fit
        session.post(
            base + "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/",
            data=_FORM_FIELDS,
            allow_redirects=True,
        )

        # Poll /StatusAndResults/ until completion (up to 240s)
        poll_deadline = time.time() + 240
        while time.time() < poll_deadline:
            r = session.get(base + "/StatusAndResults/")
            body = r.text
            if "REDIRECT" not in body and "REFRESH" not in body.upper():
                # Done — check expected strings
                for expected in _EXPECTED_STRINGS:
                    if expected not in body:
                        print(
                            f"ERROR: expected '{expected}' not in results",
                            file=sys.stderr,
                        )
                        return 1
                print("SMOKE OK: fit completed and numeric asserts passed")
                return 0
            time.sleep(3)

        print("ERROR: fit did not complete within 240s", file=sys.stderr)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(run_smoke())
```

Note: this uses `python -m waitress` which requires waitress to be installed. That happens in Phase 4. If running this before Phase 4, install waitress manually via `uv add waitress` first.

- [ ] **Step 3: Commit**

Do NOT run the smoke script yet — waitress isn't a dependency until Phase 4. The script is committed now to unblock parallel review but executed in Phase 4's verification task.

```bash
git add scripts/__init__.py scripts/smoke_test.py
git commit -m "$(cat <<'EOF'
Add scripts/smoke_test.py for end-to-end cross-platform verification

Replaces FunkLoad's value at ~5% of its line count. Starts Waitress,
POSTs a 2D polynomial fit against the sample data, polls until
completion, asserts on known coefficients. Runnable on any OS via
'uv run python scripts/smoke_test.py' once waitress is installed
(Phase 4).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 29: Phase 2 verification — manage.py check and full test suite

**Files:** verification only.

- [ ] **Step 1: Full test suite**

Run: `uv run pytest tests/ -v`
Expected: all tests PASS (platform_compat + pickle-spike + payload round-trip).

- [ ] **Step 2: Django check**

Run: `uv run python manage.py check`
Expected: clean.

- [ ] **Step 3: Confirm no os.fork call sites remain in LongRunningProcessView**

Run: `grep -n "os\.fork\|os\._exit" zunzun/views.py`
Expected: only `os.fork()` in `HomePageView` (line 494) and its corresponding `os._exit(0)` (line 530) still appear — they're Phase 3's job.

- [ ] **Step 4: Manual end-to-end on Linux/WSL (if available)**

Start the dev server, submit a fit via the web interface, verify it completes. This is qualitative verification before automated smoke runs in Phase 4.

- [ ] **Step 5: Phase 2 completion marker**

No commit — Phase 2 is complete. Proceed to Phase 3.

---

# Phase 3 — Finish spawn migration

Apply the same pattern to the remaining two fork sites: the `HomePageView` housekeeping fork and the `FitUserDefinedFunction` inner fork.

## Task 30: Replace os.fork() in HomePageView with Process(spawn)

**Files:**
- Modify: `zunzun/views.py` (lines ~492-530)

- [ ] **Step 1: Add the housekeeping child entrypoint at the top of views.py**

Near the top of `zunzun/views.py`, after the imports and before the first view function, add:

```python
def _housekeeping_child(temp_dir: str, max_size_mb: int) -> None:
    """Top-level entrypoint for the HomePageView housekeeping fork.

    Must be module-level (not nested) for spawn to pickle it.
    Clears expired sessions and trims temp/ when it exceeds
    max_size_mb.
    """
    from django.contrib.sessions.backends.db import SessionStore as _SessionStore
    try:
        _SessionStore().clear_expired()

        totalDirSize = 0
        dirInfo = []
        for item in os.listdir(temp_dir):
            itempath = os.path.join(temp_dir, item)
            if os.path.isfile(itempath):
                fileSize = os.path.getsize(itempath)
                fileMtime = os.path.getmtime(itempath)
                dirInfo.append([fileMtime, fileSize, item])
                totalDirSize += fileSize

        maxSize = max_size_mb * 1000000

        if totalDirSize > maxSize:
            totalReduction = 0
            reductionAmount = (totalDirSize - maxSize) + (maxSize * 0.25)
            dirInfo.sort()
            for fileItem in dirInfo:
                if totalReduction < reductionAmount:
                    totalReduction += fileItem[1]
                    try:
                        os.remove(os.path.join(temp_dir, fileItem[2]))
                    except Exception:
                        pass
                else:
                    break
    except Exception:
        pass
```

- [ ] **Step 2: Replace the fork block in HomePageView**

Find the block inside `HomePageView` (around line 494):
```python
    processID_1 = os.fork()
    if processID_1 == 0: # child process, kill when done
        try:
            # whenever the home page is loaded, clear expired sessions
            SessionStore().clear_expired()
            # ... (the full housekeeping body) ...
        finally:
            os._exit(0) # kill this child process
```

Replace the entire block with:
```python
    db.connections.close_all()
    close_old_connections()
    ctx = multiprocessing.get_context("spawn")
    ctx.Process(
        target=_housekeeping_child,
        args=(settings.TEMP_FILES_DIR, settings.MAX_TEMP_DIR_SIZE_IN_MBYTES),
        daemon=True,
    ).start()
```

- [ ] **Step 3: Verify**

Run: `uv run python manage.py check`
Run: `uv run pytest tests/ -v`
Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add zunzun/views.py
git commit -m "$(cat <<'EOF'
Replace os.fork() in HomePageView housekeeping with Process(spawn)

Final fork site in views.py. Housekeeping (expired-session clear,
temp/ dir trim) now runs in a daemon Process spawned with the
cross-platform context.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 31: Replace FitUserDefinedFunction inner fork with Process(spawn)

**Files:**
- Modify: `zunzun/LongRunningProcess/FitUserDefinedFunction.py` (around line 67)

- [ ] **Step 1: Read the existing inner fork**

Open `zunzun/LongRunningProcess/FitUserDefinedFunction.py`. Locate the inner fork block (search for `os.fork`). Understand: it forks to isolate compilation of user-supplied Python, so infinite loops or crashes in the user function don't take down the fit process.

- [ ] **Step 2: Replace with spawn-based Process**

The exact code depends on what the inner fork computes and returns. The general pattern:

Before (conceptually):
```python
pid = os.fork()
if pid == 0:
    try:
        result = compile_and_evaluate_user_function(udf_text)
        _write_result_to_tempfile(result)
    finally:
        os._exit(0)
else:
    os.waitpid(pid, 0)
    result = _read_result_from_tempfile()
```

After:
```python
import multiprocessing
import tempfile
import pickle

def _compile_udf_child(udf_text, result_path):
    try:
        result = compile_and_evaluate_user_function(udf_text)
    except Exception as e:
        result = e
    with open(result_path, "wb") as f:
        pickle.dump(result, f)

result_path = tempfile.NamedTemporaryFile(suffix=".pkl", delete=False).name
ctx = multiprocessing.get_context("spawn")
proc = ctx.Process(target=_compile_udf_child, args=(udf_text, result_path))
proc.start()
proc.join(timeout=30)  # bound UDF compile to 30 seconds
if proc.is_alive():
    proc.terminate()
    raise RuntimeError("User-defined function compilation timed out")

with open(result_path, "rb") as f:
    result = pickle.load(f)
if isinstance(result, Exception):
    raise result
```

Adapt the surrounding code to match what the original inner fork actually did — read the whole function before editing, and preserve its contract (what it returns, how errors propagate).

Remove the original `os._exit(0)` at the end of the inner child.

- [ ] **Step 3: Verify**

Run: `uv run python manage.py check`
Run: `uv run pytest tests/ -v`
Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add zunzun/LongRunningProcess/FitUserDefinedFunction.py
git commit -m "$(cat <<'EOF'
Replace FitUserDefinedFunction inner fork with Process(spawn)

The UDF-compilation isolation (defense against infinite loops in
user-submitted code) now uses multiprocessing.Process with a
timeout, not os.fork(). Last os.fork() site in the codebase.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Confirm no os.fork calls remain**

Run: `grep -rn "os\.fork\|os\._exit" zunzun/ --include="*.py"`
Expected: zero matches outside of comments.

---

# Phase 4 — Waitress + apps.py

## Task 32: Add waitress as a default dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add waitress to the default dependencies**

Edit `pyproject.toml`. Find the `dependencies = [...]` list inside `[project]`. Add `"waitress>=3.0"` to the list:

```toml
dependencies = [
    "django>=2.2,<3.0",
    "pyeq3",
    "numpy",
    "scipy",
    "matplotlib",
    "reportlab",
    "psutil",
    "beautifulsoup4",
    "waitress>=3.0",
]
```

- [ ] **Step 2: Run uv sync to install waitress**

Run: `uv sync`
Expected: waitress installs into `.venv`.

- [ ] **Step 3: Verify waitress is importable**

Run: `uv run python -c "import waitress; print(waitress.__version__)"`
Expected: prints a version number.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
Add waitress as a default production-server dependency

Waitress is the cross-platform WSGI server (works natively on
Windows, unlike gunicorn). Becomes the recommended stack for
prod deployment on all three target OSes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 33: Create zunzun/apps.py with AppConfig.ready() hook

**Files:**
- Create: `zunzun/apps.py`
- Modify: `zunzun/__init__.py`

- [ ] **Step 1: Create zunzun/apps.py**

Write `zunzun/apps.py`:
```python
"""Django app config for zunzun.

Uses AppConfig.ready() to check for required external binaries
(mogrify, gifsicle) on startup and log a prominent warning if
they're missing. Fits still work without them; 3D animations do not.
"""
import logging

from django.apps import AppConfig

_logger = logging.getLogger(__name__)


class ZunZunConfig(AppConfig):
    name = "zunzun"

    def ready(self) -> None:
        from . import platform_compat
        missing = platform_compat.ensure_external_binaries()
        if missing:
            _logger.warning(
                "zunzunsite3: missing external binaries on PATH: %s. "
                "Fits will work, but animated GIF output will fail. "
                "Install with: apt-get install imagemagick gifsicle (Linux), "
                "brew install imagemagick gifsicle (macOS), or "
                "winget install ImageMagick.ImageMagick and winget install gifsicle.gifsicle (Windows).",
                ", ".join(missing),
            )
```

- [ ] **Step 2: Set default_app_config**

Modify `zunzun/__init__.py`:
```python
default_app_config = "zunzun.apps.ZunZunConfig"
```

(The file was previously empty; add just this one line.)

- [ ] **Step 3: Verify Django loads the AppConfig**

Run: `uv run python manage.py check`
Expected: clean. If a warning about missing `mogrify`/`gifsicle` appears, that's the AppConfig working correctly.

- [ ] **Step 4: Commit**

```bash
git add zunzun/apps.py zunzun/__init__.py
git commit -m "$(cat <<'EOF'
Add ZunZunConfig AppConfig with ready() hook for binary check

Calls platform_compat.ensure_external_binaries() on startup; logs
a platform-specific install recommendation if mogrify or gifsicle
are missing from PATH.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 34: Run scripts/smoke_test.py end-to-end

**Files:** verification only.

- [ ] **Step 1: Run the smoke test**

Run: `uv run python scripts/smoke_test.py`

Expected output: `SMOKE OK: fit completed and numeric asserts passed`

Expected exit code: 0.

If the smoke test fails:
- If ERROR is "server never became ready", check that waitress-serve starts: `uv run waitress-serve --listen=127.0.0.1:8001 wsgi:application` and ensure the homepage loads.
- If ERROR is "fit did not complete within 240s", investigate the child process (check `temp/*.log` for tracebacks from `_run_fit_child`).
- If ERROR is "expected '-5.824100E-02' not in results", the fit completed but returned different numbers — check whether sample data or default fitting config changed.

- [ ] **Step 2: Phase 4 completion marker**

No commit — proceed to Phase 5.

---

# Phase 5 — Deployment docs

## Task 35: Write docs/deployment/README.md

**Files:**
- Create: `docs/deployment/README.md`

- [ ] **Step 1: Write the overview doc**

Write `docs/deployment/README.md`:
```markdown
# Deployment recipes

Production deployment is documented per platform. Pick your target:

- [Linux](linux.md) — nginx → Waitress (or gunicorn sync workers)
- [macOS](macos.md) — nginx → Waitress, supervised by launchd
- [Windows](windows.md) — IIS + Waitress via NSSM

All three use **Waitress** as the Python WSGI server because it runs
natively on every supported OS. The reverse proxy (nginx or IIS) serves
TLS termination, static asset caching, and URL routing.

## Minimum stack

- Python 3.11 (uv-managed; see README.txt)
- `uv sync --no-dev` to install production dependencies
- A reverse proxy for TLS + static files
- A process supervisor appropriate to the OS (systemd, launchd, NSSM)
- `imagemagick` and `gifsicle` on PATH (for animated GIF output)

## Docker

If you're containerized, pick a `python:3.11-slim` base image and
follow the [Linux](linux.md) recipe inside the container. Docker
itself handles cross-platform.

## What isn't documented

- CI/CD pipeline automation — out of scope for these recipes.
- Kubernetes / orchestration — the Linux systemd unit is the reference;
  adapt to your orchestrator's unit format.
```

- [ ] **Step 2: Commit**

```bash
git add docs/deployment/README.md
git commit -m "$(cat <<'EOF'
Add docs/deployment/README.md as deployment overview

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 36: Write docs/deployment/linux.md

**Files:**
- Create: `docs/deployment/linux.md`

- [ ] **Step 1: Write the Linux recipe**

Write `docs/deployment/linux.md`:
```markdown
# Linux deployment

Tested configuration: Ubuntu 22.04 / 24.04 LTS. Adapt package names
and paths for other distributions.

## System dependencies

```bash
sudo apt-get install -y python3-venv nginx imagemagick gifsicle
# uv installer (choose one):
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Site installation

```bash
sudo mkdir -p /var/www/zunzunsite3
sudo chown $USER:www-data /var/www/zunzunsite3
cd /var/www/zunzunsite3
git clone https://bitbucket.org/zunzuncode/zunzunsite3.git .
uv sync --no-dev
uv run python manage.py migrate
```

## Stack A (recommended): nginx → Waitress

### systemd unit

Write `/etc/systemd/system/zunzunsite3.service`:

```ini
[Unit]
Description=ZunZunSite3 (Waitress)
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/zunzunsite3
ExecStart=/var/www/zunzunsite3/.venv/bin/waitress-serve --listen=127.0.0.1:8000 wsgi:application
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zunzunsite3
sudo systemctl status zunzunsite3
```

### nginx config

Write `/etc/nginx/sites-available/zunzunsite3`:

```nginx
server {
    listen 80;
    server_name zunzunsite3.example.com;

    # Serve static files directly (bypasses Waitress)
    location /temp/static_images/ {
        alias /var/www/zunzunsite3/temp/static_images/;
        expires 7d;
    }

    # Pass everything else to Waitress
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

Enable:
```bash
sudo ln -s /etc/nginx/sites-available/zunzunsite3 /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

For TLS, use certbot: `sudo certbot --nginx -d zunzunsite3.example.com`.

## Stack B: nginx → gunicorn (sync workers ONLY)

`gunicorn` works on Linux but requires sync workers because zunzun's
fork/spawn pattern is not safe under multi-threaded gunicorn workers.

Add `gunicorn` to dev deps or install separately, then:

```bash
uv run gunicorn --workers 4 --worker-class sync --threads 1 \
    --bind 127.0.0.1:8000 wsgi:application
```

**Critical:** `--worker-class sync --threads 1`. If you use `gthread`
or set `--threads >1`, the multi-threaded worker reintroduces the
fork-safety hazard.

Apache + mod_wsgi works with the same `threads=1` constraint on the
`WSGIDaemonProcess` directive.

## Operational notes

- Logs: `journalctl -u zunzunsite3 -f`
- Restart: `sudo systemctl restart zunzunsite3`
- Temp-directory trim happens automatically on home-page loads; set
  `MAX_TEMP_DIR_SIZE_IN_MBYTES` in `settings.py` (default 500).
- Child processes spawned during fits appear as `python3` children
  of the Waitress process in `ps aux`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/deployment/linux.md
git commit -m "$(cat <<'EOF'
Add docs/deployment/linux.md — nginx + Waitress (primary), gunicorn sync (alternate)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 37: Write docs/deployment/macos.md

**Files:**
- Create: `docs/deployment/macos.md`

- [ ] **Step 1: Write the macOS recipe**

Write `docs/deployment/macos.md`:
```markdown
# macOS deployment

**Status:** Author had no Mac hardware available during migration;
the launchd plist is written by structural extension from the Linux
systemd unit. Verify on a real macOS box before relying on this.

## System dependencies

```bash
brew install python@3.11 nginx imagemagick gifsicle
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Site installation

```bash
sudo mkdir -p /usr/local/var/zunzunsite3
sudo chown $USER:staff /usr/local/var/zunzunsite3
cd /usr/local/var/zunzunsite3
git clone https://bitbucket.org/zunzuncode/zunzunsite3.git .
uv sync --no-dev
uv run python manage.py migrate
```

## launchd plist

Write `~/Library/LaunchAgents/com.zunzunsite3.waitress.plist` (or
`/Library/LaunchDaemons/` for system-wide):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.zunzunsite3.waitress</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/var/zunzunsite3/.venv/bin/waitress-serve</string>
        <string>--listen=127.0.0.1:8000</string>
        <string>wsgi:application</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/usr/local/var/zunzunsite3</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/usr/local/var/zunzunsite3/waitress.log</string>

    <key>StandardErrorPath</key>
    <string>/usr/local/var/zunzunsite3/waitress.err</string>
</dict>
</plist>
```

Load:
```bash
launchctl load ~/Library/LaunchAgents/com.zunzunsite3.waitress.plist
launchctl start com.zunzunsite3.waitress
```

## nginx config

Same as Linux (see [linux.md](linux.md#nginx-config)). Homebrew's
nginx config lives at `/usr/local/etc/nginx/servers/`.

## Operational notes

- Logs: `/usr/local/var/zunzunsite3/waitress.log` and `waitress.err`.
- Restart: `launchctl stop com.zunzunsite3.waitress && launchctl start com.zunzunsite3.waitress`.
- macOS has `os.fork()` and `os.nice()` natively, but the spawn
  migration still uses spawn for uniformity and to avoid the
  multi-threaded fork hazard under Waitress.
```

- [ ] **Step 2: Commit**

```bash
git add docs/deployment/macos.md
git commit -m "$(cat <<'EOF'
Add docs/deployment/macos.md

Launchd plist + nginx + Waitress recipe. Flagged as unverified on
real macOS hardware per spec §8.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 38: Write docs/deployment/windows.md

**Files:**
- Create: `docs/deployment/windows.md`

- [ ] **Step 1: Write the Windows recipe**

Write `docs/deployment/windows.md`:
```markdown
# Windows deployment

Tested on Windows 11 Pro + IIS 10. Uses IIS as the front-end reverse
proxy, Waitress as the Python WSGI server, and NSSM to run Waitress
as a Windows Service.

## Phase 1 — System prerequisites

### Install uv and Python

```powershell
winget install --id=astral-sh.uv
uv python install 3.11
```

### Install mogrify and gifsicle

```powershell
winget install ImageMagick.ImageMagick
# gifsicle: if the winget package is unavailable, download from
# https://eternallybored.org/misc/gifsicle/ and place gifsicle.exe
# somewhere on PATH.
```

Verify PATH:
```powershell
where magick
where gifsicle
```

Both should print a path. If not, re-check PATH env var.

## Phase 2 — Site installation

Choose a path outside `C:\inetpub` (IIS doesn't need it there — ARR will proxy):

```powershell
mkdir C:\sites\zunzunsite3
cd C:\sites\zunzunsite3
git clone https://bitbucket.org/zunzuncode/zunzunsite3.git .
uv sync --no-dev
uv run python manage.py migrate
```

Grant the service account that will run Waitress (often `NT AUTHORITY\NetworkService` or a dedicated local account) read access on all files and write access on `temp\` and `session_db\`:

```powershell
icacls C:\sites\zunzunsite3\temp /grant "NT AUTHORITY\NetworkService:(OI)(CI)M"
icacls C:\sites\zunzunsite3\session_db /grant "NT AUTHORITY\NetworkService:(OI)(CI)M"
```

## Phase 3 — Waitress as a Windows Service via NSSM

Download NSSM from https://nssm.cc/ and place `nssm.exe` in a known
location.

Install the service:
```powershell
nssm install zunzunsite3 "C:\sites\zunzunsite3\.venv\Scripts\waitress-serve.exe" ^
    "--listen=127.0.0.1:8000" "wsgi:application"
nssm set zunzunsite3 AppDirectory C:\sites\zunzunsite3
nssm set zunzunsite3 AppStdout C:\sites\zunzunsite3\waitress.log
nssm set zunzunsite3 AppStderr C:\sites\zunzunsite3\waitress.err
nssm set zunzunsite3 Start SERVICE_AUTO_START
nssm start zunzunsite3
```

Verify:
```powershell
curl http://127.0.0.1:8000/
```
Should return the homepage HTML.

## Phase 4 — IIS reverse proxy

### Install IIS + required modules

Via PowerShell (admin):
```powershell
Install-WindowsFeature -Name Web-Server, Web-Mgmt-Console
```

Then download and install:
- URL Rewrite 2.1 — https://www.iis.net/downloads/microsoft/url-rewrite
- Application Request Routing 3.0 — https://www.iis.net/downloads/microsoft/application-request-routing

### Enable proxy in ARR

Open IIS Manager → server node (top-level) → Application Request
Routing Cache → Server Proxy Settings → Check "Enable proxy" → Apply.

### Create site and rewrite rule

In IIS Manager:
1. Sites → Add Website → name "zunzunsite3", physical path `C:\sites\zunzunsite3\temp` (for direct static serving), binding port 80 (or 443 for TLS).
2. Select the site → URL Rewrite → Add Rule → Reverse Proxy Rules → Reverse Proxy.
3. Inbound rule: enter `localhost:8000` as the backend server. Apply.

This proxies all traffic not matching a local file (which IIS serves
directly — including the static images in `temp\static_images\`) to
Waitress on port 8000.

## Phase 5 — Operational notes

- Logs: `C:\sites\zunzunsite3\waitress.log` and `waitress.err`; IIS
  logs are under `C:\inetpub\logs\LogFiles\`.
- Restart Waitress: `nssm restart zunzunsite3` or via Services.msc.
- Child processes from fits: observable as `python.exe` children of
  the Waitress service in Task Manager → Details.
- **Windows Defender exclusion recommended**: Defender scanning
  `.venv\` aggressively can cause fit latency spikes. Add
  `C:\sites\zunzunsite3\.venv\` as a scan exclusion in Defender
  settings for real-time protection.
```

- [ ] **Step 2: Commit**

```bash
git add docs/deployment/windows.md
git commit -m "$(cat <<'EOF'
Add docs/deployment/windows.md — IIS + Waitress via NSSM

Five-phase walkthrough: prereqs, site layout, NSSM service install,
IIS reverse proxy, operational notes. The most detailed recipe
because Windows Django deployment has more moving parts than Unix.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 39: Update README.txt

**Files:**
- Modify: `README.txt`

- [ ] **Step 1: Remove the Unix-only warning and add deployment pointer**

Edit `README.txt`. Find the block:
```
NOTES: the code uses Unix-style process forking, and this is not
available on the Windows operating system.

My tests show that while both mod_wsgi and gunicorn work fine for
Django production servers, the uwsgi process model would not allow
os.fork() calls to work as required for this software.
```

Replace with:
```
Cross-platform: zunzunsite3 runs on Linux, macOS, and Windows via
multiprocessing.Process(spawn). The original os.fork() architecture
has been replaced as of April 2026.

For production deployment recipes per platform, see docs/deployment/.

If you have existing deployments: gunicorn still works on Linux/macOS
with --worker-class sync --threads 1 (multi-threaded workers reintroduce
fork-safety hazards in view code that spawns subprocesses). Waitress
is the recommended cross-platform stack.

The FunkLoad functional tests in funkload_tests/ require a separate
install. FunkLoad's setup.py depends on ez_setup which has been
removed from modern setuptools, so it cannot be installed under the
uv-managed environment. scripts/smoke_test.py provides a lighter
end-to-end check using requests against a live Waitress server; see
CLAUDE.md for details.
```

- [ ] **Step 2: Commit**

```bash
git add README.txt
git commit -m "$(cat <<'EOF'
Update README.txt for cross-platform support

Removes the "not available on Windows" warning. Adds pointer to
docs/deployment/ for per-platform production recipes. Notes the
gunicorn sync-worker constraint for existing Linux deployments.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 40: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the fork-pattern section**

In `CLAUDE.md`, find the section headed `### The fork-based long-running-process pattern` (starts around "This is the single most important thing to understand..."). Rewrite the heading to `### The spawn-based long-running-process pattern` and update the text to match the post-migration reality.

Replace the entire section content with:

```markdown
### The spawn-based long-running-process pattern

This is the single most important thing to understand before modifying views or session code.

1. A POST to `/CharacterizeData/`, `/FitEquation__F__/...`, `/FunctionFinder__.__/...`, etc. lands in `LongRunningProcessView` (`zunzun/views.py`).
2. That view picks a concrete `LRP` class from `zunzun/LongRunningProcess/` by **substring-matching `request.path`** (e.g. `'UserDefinedFunction'` → `FitUserDefinedFunction`, `'Spline'` → `FitSpline`, else `FitOneEquation`). To add a new fit flow, both a URL pattern in `urls.py` and a new branch in this dispatcher are required.
3. The view calls `LRP.build_child_payload()` to produce a picklable `ChildPayload` dataclass carrying only what the child needs (session keys, dimensionality, DataObject, equation, subclass-specific flags). See `zunzun/LongRunningProcess/child_payload.py`.
4. The parent calls `multiprocessing.Process(target=_run_fit_child, args=(payload,))` using the **spawn** start method (mandatory on Windows, safest across all platforms under multi-threaded WSGI servers like Waitress).
5. The parent returns `HttpResponseRedirect('/StatusAndResults/')`. The **child** (fresh Python interpreter) imports the LRP class from the payload's `lrp_class_path`, calls `apply_child_payload()` to hydrate state, runs `PerformAllWork()`, and returns.
6. `StatusView` polls every 3s via `<meta http-equiv=REFRESH>`; when the child writes `redirectToResultsFileOrURL` into the status session, `StatusView` serves the generated file or issues a redirect.

Consequences:

- **The site runs on Linux, macOS, and Windows.** Waitress is the recommended cross-platform WSGI server; see `docs/deployment/`.
- Platform-specific calls (load average, process priority, zombie reap, shellouts for mogrify/gifsicle/rm) live in `zunzun/platform_compat.py` — never call `os.getloadavg`, `/proc`, `vmstat`, or `os.popen` directly from view or LRP code.
- `CommonToAllViews()` reaps completed children via `platform_compat.reap_completed_children()` on every request; `HomePageView` spawns a daemon housekeeping process to clear expired sessions and trim `temp/` when it exceeds `MAX_TEMP_DIR_SIZE_IN_MBYTES` (default 500).
- `os.fork()` and `os._exit()` no longer appear in the codebase. Adding them will break Windows compatibility; prefer `multiprocessing.Process(spawn)` and plain `return` respectively.
```

- [ ] **Step 2: Update the "Running the site" section**

Find the section headed `## Running the site` and add after the existing `uv run python manage.py runserver` line:

```markdown
For production, use Waitress (cross-platform):

```bash
uv run waitress-serve --listen=127.0.0.1:8000 wsgi:application
```
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
Update CLAUDE.md for the spawn-based architecture

Rewrites the "fork-based long-running-process pattern" section to
describe the post-migration spawn architecture with ChildPayload.
Adds Waitress as the documented production server command.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Step 1: Full test suite on all three platforms**

On Linux:
```bash
uv run pytest tests/ -v
uv run python scripts/smoke_test.py
```

On macOS:
```bash
uv run pytest tests/ -v
uv run python scripts/smoke_test.py
```

On Windows:
```powershell
uv run pytest tests/ -v
uv run python scripts/smoke_test.py
```

All three should pass. If any platform fails: diagnose from the
error, fix, re-run.

- [ ] **Step 2: Verify definition-of-done items from spec §10**

1. `uv sync && uv run python manage.py check && uv run python manage.py migrate` on all three OSes — PASS
2. `scripts/smoke_test.py` exits 0 on all three OSes — PASS
3. `docs/deployment/{linux.md,macos.md,windows.md}` exist with configs — PASS
4. `platform_compat.ensure_external_binaries()` correctly reports missing mogrify/gifsicle — verified by AppConfig warning behavior
5. README.txt no longer contains "the code uses Unix-style process forking, and this is not available on the Windows operating system." — PASS (Task 39)

- [ ] **Step 3: Merge to master**

If working on a feature branch, merge to master. Otherwise, the per-phase commits on master already reflect the migration.

```bash
git log --oneline | head -45
```
Expected: 40 new commits since the spec was written, each with Co-Authored-By trailer.

---
