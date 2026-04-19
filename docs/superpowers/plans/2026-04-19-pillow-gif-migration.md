# Pillow GIF Animation Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ImageMagick-mogrify and gifsicle shell-outs in both 3D animation paths (`ScatterAnimation`, `SurfaceAnimation`) with `matplotlib.animation.FuncAnimation` + `matplotlib.animation.PillowWriter`. Drop both system binaries as dependencies; animated GIF generation becomes pure-Python.

**Architecture:** Nine phases on a dedicated worktree. Phase 1 adds unit tests against the *current* mogrify+gifsicle implementation (TDD gate — confirms test shape is correct before we touch the code under test). Phases 2–3 refactor the two animation classes one at a time. Phase 4 prunes `platform_compat` and updates `apps.py` + affected `test_platform_compat.py` assertions. Phase 5 updates `pyproject.toml` + prose docs. Phase 6 updates `TODO.md`. Phase 7 is your manual visual QA. Phase 8 is the local merge. Zero push to origin.

**Tech Stack:** Python 3.14.4, Django 6.0.4, matplotlib 3.10.8 (`FuncAnimation`, `PillowWriter`), Pillow 12.2.0, pytest + pytest-django, uv for dependency management.

**Reference:** Design spec at `docs/superpowers/specs/2026-04-19-pillow-gif-design.md` (commit `2761f14`).

---

## Global conventions

- **Test command:** `UV_LINK_MODE=copy uv run pytest tests/ -v`
- **Smoke command:** `UV_LINK_MODE=copy uv run python scripts/smoke_test.py` (8 scenarios, ~15 min on Windows)
- **Django check:** `UV_LINK_MODE=copy uv run python manage.py check`
- **Every `uv` invocation requires `UV_LINK_MODE=copy`** — Dropbox-backed filesystem breaks uv's default hardlink mode otherwise.
- **Commit style:** short subject matching repo style, body with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.
- **Hook awareness:** `.claude/hooks/py_compile_check.py` runs on every `.py` Edit/Write; it blocks commits introducing syntax errors.
- **Working directory:** All phases execute inside `C:\Dropbox\git\zunzunsite3-pillow-gif\` (worktree created in Task 1).
- **Fresh worktree:** requires `UV_LINK_MODE=copy uv run python manage.py migrate` once to create `session_db/db.sqlite3` (gitignored).
- **Animation smoke gate:** smoke cannot exercise animation paths (requires 3D fit, which deadlocks per existing `TODO.md` entry). Animation correctness gates via pytest unit tests + user's manual visual QA only.

## File structure

Files touched by this plan:

| File | Responsibility | Task |
|---|---|---|
| `tests/test_animation.py` | New. Two unit tests producing valid animated GIFs from both classes. | Task 2, 3, 4 |
| `zunzun/LongRunningProcess/ReportsAndGraphs.py` | Rewrite both animation classes' `CreateReportOutput` / `CreateCharacterizerOutput`. | Task 3, 4 |
| `zunzun/platform_compat.py` | Delete `resolve_mogrify_command`; prune `ensure_external_binaries`. | Task 5 |
| `zunzun/apps.py` | Update startup warning message to remove imagemagick/gifsicle specifics. | Task 5 |
| `tests/test_platform_compat.py` | Delete/rewrite tests for the pruned functions. | Task 5 |
| `pyproject.toml` | Add `"pillow"` to runtime deps. | Task 6 |
| `CLAUDE.md` | Rewrite "System dependencies" paragraph. | Task 6 |
| `README.txt` | Delete lines 16–19 (imagemagick/gifsicle install block). | Task 6 |
| `docs/deployment/linux.md`, `macos.md`, `windows.md` | Strike `imagemagick` and `gifsicle` from install commands. | Task 6 |
| `TODO.md` | Add "Animation smoke coverage" entry; cross-reference from 3D deadlock entry. | Task 7 |

## Phasing overview

| Phase | Tasks | Output |
|---|---|---|
| **0 — Setup** | 1 | Worktree + baseline green |
| **1 — Unit tests first (TDD gate)** | 2 | `tests/test_animation.py` passes on current mogrify+gifsicle impl |
| **2 — Refactor ScatterAnimation** | 3 | First animation class uses PillowWriter; test stays green |
| **3 — Refactor SurfaceAnimation** | 4 | Second animation class uses PillowWriter; test stays green |
| **4 — Prune platform_compat + apps.py + tests** | 5 | Dead mogrify/gifsicle code + tests removed |
| **5 — pyproject.toml + docs** | 6 | `pillow` explicit dep; all docs reflect new reality |
| **6 — TODO.md** | 7 | Documented animation-smoke-coverage gap |
| **7 — Manual visual QA** | 8 | User verifies animated GIFs on the live site |
| **8 — Merge** | 9 | Local merge to master, no push |

**Expected final test count:** 79 (82 current − 5 deleted platform_compat tests + 2 new animation tests). Detail in Task 5.

---

# Phase 0 — Setup

## Task 1: Create worktree and baseline

**Files:**
- None — git + filesystem only

- [ ] **Step 1: Create worktree + branch**

From `C:\Dropbox\git\zunzunsite3\`:
```bash
git worktree add ../zunzunsite3-pillow-gif -b pillow-gif-migration master
```

Expected: `Preparing worktree … HEAD is now at <current-master-commit>`.

- [ ] **Step 2: Verify worktree state**

From `C:\Dropbox\git\zunzunsite3-pillow-gif\`:
```bash
git status
git branch --show-current
```

Expected: clean working tree, `pillow-gif-migration`.

- [ ] **Step 3: Install deps + create session DB**

```bash
UV_LINK_MODE=copy uv sync
UV_LINK_MODE=copy uv run python manage.py migrate
```

Expected: clean install; `sessions.0001_initial` applied.

- [ ] **Step 4: Baseline pytest**

```bash
UV_LINK_MODE=copy uv run pytest tests/ -v 2>&1 | tail -5
```

Expected: `82 passed, 1 warning`.

- [ ] **Step 5: Audit remaining `run_tool` and `remove_files_matching` callers**

```bash
grep -rn "run_tool\|remove_files_matching" zunzun/ --include="*.py"
```

Expected output:
```
zunzun/platform_compat.py:145:def run_tool(...)
zunzun/platform_compat.py:203:def remove_files_matching(...)
zunzun/LongRunningProcess/ReportsAndGraphs.py:1514: platform_compat.run_tool(
zunzun/LongRunningProcess/ReportsAndGraphs.py:1522: platform_compat.run_tool(
zunzun/LongRunningProcess/ReportsAndGraphs.py:1527: platform_compat.remove_files_matching(
zunzun/LongRunningProcess/ReportsAndGraphs.py:1582: platform_compat.run_tool(
zunzun/LongRunningProcess/ReportsAndGraphs.py:1590: platform_compat.run_tool(
zunzun/LongRunningProcess/ReportsAndGraphs.py:1595: platform_compat.remove_files_matching(
```

Confirmation: every runtime call site is inside the two animation classes that Phases 2–3 rewrite. Post-migration, `run_tool` and `remove_files_matching` have no runtime callers; spec §5.2 says keep them as generic utilities. Retain.

No commit in Task 1.

---

# Phase 1 — Unit tests first (TDD gate)

## Task 2: Add test_animation.py against current mogrify+gifsicle code

**Files:**
- Create: `tests/test_animation.py`

- [ ] **Step 1: Read the DataObject interface**

```bash
grep -n "def __init__\|self\." zunzun/LongRunningProcess/DataObject.py | head -40
```

Scan for attributes referenced in `ScatterAnimation.CreateCharacterizerOutput` (lines 1492–1531) and `SurfaceAnimation.CreateReportOutput` (lines 1559–1599):
- `dimensionality`, `animationHeight`, `animationWidth`, `altimuth3D`
- `graphHeight`, `graphWidth` (assigned from animationHeight/Width inside the methods)
- `uniqueString`, `IndependentDataArray`, `DependentDataArray`
- `equation` (for SurfaceAnimation — surface plot requires solved coefficients)
- `CalculateGraphBoundaries()` method

- [ ] **Step 2: Create the test file**

Write `tests/test_animation.py`:
```python
"""Unit tests for 3D animation GIF generation.

Both animation classes (ScatterAnimation, SurfaceAnimation) build a
matplotlib 3D figure, rotate the camera through 360°, and write an
animated GIF to disk. These tests drive each class end-to-end with a
minimal DataObject, and assert the produced file is a valid multi-frame
animated GIF.

No Django, no spawn, no session DB — just matplotlib + Pillow.
"""
import os

import numpy
import pytest
from PIL import Image

from zunzun.LongRunningProcess import ReportsAndGraphs
from zunzun.LongRunningProcess.DataObject import DataObject


def _build_3d_dataobject(tmp_path):
    """Minimal DataObject for a 3D animation test.

    Hand-populates the attributes the animation classes actually read,
    using a small synthetic dataset. 12-point 3D grid with smooth Z
    values is enough for matplotlib to render a visible scatter/surface.
    """
    obj = DataObject()
    obj.dimensionality = 3
    obj.animationHeight = 240
    obj.animationWidth = 320
    obj.graphHeight = 240
    obj.graphWidth = 320
    obj.altimuth3D = 20
    obj.uniqueString = "testanim"

    # 12-point 3D grid: X,Y each spans three values, Z = X + 2*Y
    x = numpy.array([1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 3.0, 3.0, 3.0, 4.0, 4.0, 4.0])
    y = numpy.array([1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 1.0, 2.0, 3.0])
    z = x + 2.0 * y

    obj.IndependentDataArray = numpy.array([x, y])
    obj.DependentDataArray = z

    # Graph-boundary attributes (normally computed by CalculateGraphBoundaries)
    obj.minX, obj.maxX = float(x.min()), float(x.max())
    obj.minY, obj.maxY = float(y.min()), float(y.max())
    obj.minZ, obj.maxZ = float(z.min()), float(z.max())

    return obj


@pytest.fixture
def settings_temp_dir(tmp_path, settings):
    """Point settings.TEMP_FILES_DIR and STATIC_URL at a pytest tmp_path.

    Animation classes build physicalFileLocation as
    f'{settings.TEMP_FILES_DIR}/{uniqueAnchorName}{uniqueString}.gif';
    redirecting it per-test keeps the real temp/ directory clean.
    """
    settings.TEMP_FILES_DIR = str(tmp_path)
    settings.STATIC_URL = "/temp/"
    return tmp_path


@pytest.mark.django_db
def test_scatter_animation_produces_valid_gif(settings_temp_dir):
    """ScatterAnimation renders a rotating 3D scatter GIF."""
    dataobject = _build_3d_dataobject(settings_temp_dir)

    animation = ReportsAndGraphs.ScatterAnimation(dataobject)
    animation.animationFrameSeparation = 60  # 6 frames for fast test
    animation.PrepareForCharacterizerOutput()

    assert animation.physicalFileLocation, \
        "PrepareForCharacterizerOutput did not set physicalFileLocation"

    animation.CreateCharacterizerOutput()

    assert os.path.exists(animation.physicalFileLocation), \
        f"GIF not created at {animation.physicalFileLocation}"

    with Image.open(animation.physicalFileLocation) as img:
        assert img.format == "GIF", f"Expected GIF, got {img.format}"
        # 360/60 = 6 frames minimum
        assert img.n_frames >= 2, f"Expected ≥2 frames, got {img.n_frames}"


@pytest.mark.django_db
def test_surface_animation_produces_valid_gif(settings_temp_dir):
    """SurfaceAnimation renders a rotating 3D fitted-surface GIF.

    Requires the DataObject's equation to have solved coefficients. We
    stub a 3D Linear polynomial (Z = a + b*X + c*Y) with known values.
    """
    import pyeq3
    dataobject = _build_3d_dataobject(settings_temp_dir)

    equation = pyeq3.Models_3D.Polynomial.Linear()
    equation.solvedCoefficients = numpy.array([0.0, 1.0, 2.0])  # matches Z=X+2Y
    equation.dataCache = pyeq3.dataCache()
    equation.dataCache.independentData = dataobject.IndependentDataArray
    equation.dataCache.dependentData = dataobject.DependentDataArray
    dataobject.equation = equation

    animation = ReportsAndGraphs.SurfaceAnimation(dataobject)
    animation.animationFrameSeparation = 60  # 6 frames for fast test
    animation.PrepareForReportOutput()

    assert animation.physicalFileLocation, \
        "PrepareForReportOutput did not set physicalFileLocation"

    animation.CreateReportOutput()

    assert os.path.exists(animation.physicalFileLocation), \
        f"GIF not created at {animation.physicalFileLocation}"

    with Image.open(animation.physicalFileLocation) as img:
        assert img.format == "GIF"
        assert img.n_frames >= 2
```

- [ ] **Step 3: Run tests against current (mogrify+gifsicle) code**

```bash
UV_LINK_MODE=copy uv run pytest tests/test_animation.py -v
```

Expected: both tests PASS. This confirms:
1. The stub `DataObject` has enough attributes to drive both animation classes end-to-end.
2. mogrify and gifsicle are working on this machine (they must be — baseline smoke passed).
3. The test contract (`n_frames >= 2`, `format == "GIF"`) is satisfied by the current mogrify+gifsicle output.

**If tests fail:** diagnose which stub attribute is missing. Common culprits: `DataObject.__init__` sets some attribute names we didn't stub (compare your stub against a real `DataObject` produced by a smoke run — save a real instance with `pickle.dumps` for comparison if needed). Add missing attributes iteratively. Do NOT proceed until both tests are green against the CURRENT code.

**If ScatterAnimation/SurfaceAnimation raise an exception inside their try/except:** the exception is swallowed and logged to `temp/{pid}.log`. Check that file; the unit tests will pass even when the animation silently fails (bug in the current try/except wrap). Use `assert os.path.exists(...)` to catch this — the GIF file won't exist on silent failure.

- [ ] **Step 4: Commit the tests**

```bash
git add tests/test_animation.py
git commit -m "$(cat <<'EOF'
Add unit tests for ScatterAnimation and SurfaceAnimation

Both tests build a minimal 3D DataObject, drive the animation
class end-to-end, and assert the output is a valid multi-frame
animated GIF. Tests pass on the current mogrify+gifsicle impl;
they will remain the acceptance gate when Phase 2–3 refactor
each class to use matplotlib.animation.PillowWriter.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 2 — Refactor ScatterAnimation

## Task 3: Rewrite ScatterAnimation with FuncAnimation + PillowWriter

**Files:**
- Modify: `zunzun/LongRunningProcess/ReportsAndGraphs.py` (lines ~1492–1531)

- [ ] **Step 1: Add FuncAnimation + PillowWriter import**

Near the top of `zunzun/LongRunningProcess/ReportsAndGraphs.py`, add the import. Find the existing matplotlib imports (likely near the top of the file) and add:
```python
from matplotlib.animation import FuncAnimation, PillowWriter
```

If there are no existing matplotlib imports at module level (matplotlib is imported inside functions for memory reasons), add the above as a new line with its own comment:
```python
# matplotlib animation helpers used by ScatterAnimation / SurfaceAnimation
from matplotlib.animation import FuncAnimation, PillowWriter
```

- [ ] **Step 2: Rewrite `ScatterAnimation.CreateCharacterizerOutput`**

Current content (lines ~1492–1531):
```python
    def CreateCharacterizerOutput(self):
        from . import MatplotlibGraphs_3D
        
        self.dataObject.graphHeight = self.dataObject.animationHeight
        self.dataObject.graphWidth = self.dataObject.animationWidth
        self.dataObject.CalculateGraphBoundaries()
        
        try:
            [fig, ax, plt] = eval(self.functionString + '(self.dataObject, None)')

            for i in range(0,360, self.animationFrameSeparation): 
                padstr = ''
                if i < 100:
                    padstr = '0'
                if i  < 10:
                    padstr = '00'

                ax.view_init(elev=self.dataObject.altimuth3D, azim=i)
                frameName = self.physicalFileLocation[:-4] + '__' + padstr + str(i) + ".png"
                fig.savefig(frameName, format = 'png')
                
                # convert PNG file to GIF for gifsicle
                platform_compat.run_tool(
                    platform_compat.resolve_mogrify_command(),
                    ['-format', 'gif', frameName],
                )

            plt.close('all')
            import glob as _glob
            _frames = sorted(_glob.glob(self.physicalFileLocation[:-4] + '__*gif'))
            platform_compat.run_tool(
                'gifsicle',
                ['--colors', '256', '--loopcount', *_frames],
                stdout_file=self.physicalFileLocation,
            )
            platform_compat.remove_files_matching(self.physicalFileLocation[:-4] + '__*')
        except:
            import logging
            logging.basicConfig(filename = os.path.join(settings.TEMP_FILES_DIR,  str(os.getpid()) + '.log'),level=logging.DEBUG)
            logging.exception('Exception creating GIF animation')
```

Replace with:
```python
    def CreateCharacterizerOutput(self):
        from . import MatplotlibGraphs_3D

        self.dataObject.graphHeight = self.dataObject.animationHeight
        self.dataObject.graphWidth = self.dataObject.animationWidth
        self.dataObject.CalculateGraphBoundaries()

        try:
            [fig, ax, plt] = eval(self.functionString + '(self.dataObject, None)')

            elev = self.dataObject.altimuth3D
            def _update(azim):
                ax.view_init(elev=elev, azim=azim)

            anim = FuncAnimation(
                fig,
                _update,
                frames=range(0, 360, self.animationFrameSeparation),
                blit=False,
            )
            anim.save(self.physicalFileLocation, writer=PillowWriter(fps=10))
            plt.close('all')
        except:
            import logging
            logging.basicConfig(filename = os.path.join(settings.TEMP_FILES_DIR, str(os.getpid()) + '.log'), level=logging.DEBUG)
            logging.exception('Exception creating GIF animation')
```

Note: `MatplotlibGraphs_3D` import is preserved because `eval(self.functionString + ...)` relies on it being in scope (the string `'MatplotlibGraphs_3D.ScatterPlot3D'` resolves against the caller's namespace).

- [ ] **Step 3: Run the animation test**

```bash
UV_LINK_MODE=copy uv run pytest tests/test_animation.py::test_scatter_animation_produces_valid_gif -v
```

Expected: PASS. The test's `n_frames >= 2` and `format == "GIF"` assertions should still be satisfied by Pillow's output.

**If it fails with `RuntimeError: Requested MovieWriter (pillow) not available`:** Pillow's matplotlib integration didn't register. Verify with `python -c "from matplotlib.animation import PillowWriter; PillowWriter.isAvailable()"`. Unlikely given Pillow is installed.

**If it fails with an AttributeError or TypeError inside `_update`:** the closure-over-`ax` pattern has a bug. Print `type(ax)` in the test to verify matplotlib is returning a 3D axes.

- [ ] **Step 4: Run the full pytest suite**

```bash
UV_LINK_MODE=copy uv run pytest tests/ -v 2>&1 | tail -5
```

Expected: all 83 tests pass (82 original + 1 new scatter test — surface test still uses old code so it also passes).

- [ ] **Step 5: Commit**

```bash
git add zunzun/LongRunningProcess/ReportsAndGraphs.py
git commit -m "$(cat <<'EOF'
Rewrite ScatterAnimation with FuncAnimation + PillowWriter

Replaces the savefig-per-frame + mogrify PNG→GIF + gifsicle concat
pipeline with matplotlib.animation.FuncAnimation driving
matplotlib.animation.PillowWriter. Zero subprocesses, zero temp
files.

test_scatter_animation_produces_valid_gif (from Phase 1) continues
to pass, confirming the new path produces a valid multi-frame GIF.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 3 — Refactor SurfaceAnimation

## Task 4: Rewrite SurfaceAnimation with FuncAnimation + PillowWriter

**Files:**
- Modify: `zunzun/LongRunningProcess/ReportsAndGraphs.py` (lines ~1559–1599)

- [ ] **Step 1: Rewrite `SurfaceAnimation.CreateReportOutput`**

Current content (lines ~1559–1599):
```python
    def CreateReportOutput(self):
        try:
            from . import MatplotlibGraphs_3D
            
            self.dataObject.graphHeight = self.dataObject.animationHeight
            self.dataObject.graphWidth = self.dataObject.animationWidth
            self.dataObject.CalculateGraphBoundaries()

            [fig, ax, plt] = eval(self.functionString + '(self.dataObject, None)')


            for i in range(0,360,self.animationFrameSeparation): 
                padstr = ''
                if i < 100:
                    padstr = '0'
                if i  < 10:
                    padstr = '00'

                ax.view_init(elev=self.dataObject.altimuth3D, azim=i)
                frameName = self.physicalFileLocation[:-4] + '__' + padstr + str(i) + ".png"
                fig.savefig(frameName, format = 'png')
                
                # convert PNG file to GIF for gifsicle
                platform_compat.run_tool(
                    platform_compat.resolve_mogrify_command(),
                    ['-format', 'gif', frameName],
                )

            plt.close('all')
            import glob as _glob
            _frames = sorted(_glob.glob(self.physicalFileLocation[:-4] + '__*gif'))
            platform_compat.run_tool(
                'gifsicle',
                ['--colors', '256', '--loopcount', *_frames],
                stdout_file=self.physicalFileLocation,
            )
            platform_compat.remove_files_matching(self.physicalFileLocation[:-4] + '__*')
        except:
            import logging
            logging.basicConfig(filename = os.path.join(settings.TEMP_FILES_DIR,  str(os.getpid()) + '.log'),level=logging.DEBUG)
            logging.exception('Exception creating GIF animation')
```

Replace with:
```python
    def CreateReportOutput(self):
        try:
            from . import MatplotlibGraphs_3D

            self.dataObject.graphHeight = self.dataObject.animationHeight
            self.dataObject.graphWidth = self.dataObject.animationWidth
            self.dataObject.CalculateGraphBoundaries()

            [fig, ax, plt] = eval(self.functionString + '(self.dataObject, None)')

            elev = self.dataObject.altimuth3D
            def _update(azim):
                ax.view_init(elev=elev, azim=azim)

            anim = FuncAnimation(
                fig,
                _update,
                frames=range(0, 360, self.animationFrameSeparation),
                blit=False,
            )
            anim.save(self.physicalFileLocation, writer=PillowWriter(fps=10))
            plt.close('all')
        except:
            import logging
            logging.basicConfig(filename = os.path.join(settings.TEMP_FILES_DIR, str(os.getpid()) + '.log'), level=logging.DEBUG)
            logging.exception('Exception creating GIF animation')
```

- [ ] **Step 2: Run the surface test**

```bash
UV_LINK_MODE=copy uv run pytest tests/test_animation.py::test_surface_animation_produces_valid_gif -v
```

Expected: PASS.

- [ ] **Step 3: Verify mogrify/gifsicle are no longer called in the runtime code**

```bash
grep -n "mogrify\|gifsicle\|resolve_mogrify_command" zunzun/LongRunningProcess/ReportsAndGraphs.py
```

Expected: no matches. If any remain, they're dead code paths — remove them.

- [ ] **Step 4: Run full pytest**

```bash
UV_LINK_MODE=copy uv run pytest tests/ -v 2>&1 | tail -5
```

Expected: 84 tests pass (82 original + 2 new animation tests). `platform_compat` tests still pass because the functions haven't been deleted yet.

- [ ] **Step 5: Commit**

```bash
git add zunzun/LongRunningProcess/ReportsAndGraphs.py
git commit -m "$(cat <<'EOF'
Rewrite SurfaceAnimation with FuncAnimation + PillowWriter

Same shape as the Phase 2 ScatterAnimation rewrite. Both 3D
animation paths now use matplotlib's own animation machinery +
Pillow. No shellouts remain in the codebase's runtime path for
these classes.

test_surface_animation_produces_valid_gif continues to pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 4 — Prune platform_compat + apps.py + tests

## Task 5: Remove mogrify/gifsicle dead code and tests

**Files:**
- Modify: `zunzun/platform_compat.py`
- Modify: `zunzun/apps.py`
- Modify: `tests/test_platform_compat.py`

- [ ] **Step 1: Delete `resolve_mogrify_command` from `platform_compat.py`**

Find and delete the entire `def resolve_mogrify_command()` function and its docstring (lines ~176–200 in current state; anchor on `def resolve_mogrify_command` and include through the closing `)` of the FileNotFoundError raise).

- [ ] **Step 2: Simplify `ensure_external_binaries` in `platform_compat.py`**

Current content (lines ~219–240):
```python
def ensure_external_binaries() -> list[str]:
    """Report which optional external binaries are missing from PATH.

    `mogrify` is considered present if EITHER the standalone binary or
    the IM7 `magick` dispatcher is available (see resolve_mogrify_command).
    This avoids a spurious "missing: mogrify" warning on ImageMagick 7
    installs that correctly ship only `magick`.

    mogrify (part of ImageMagick) and gifsicle are used in
    ReportsAndGraphs.py to produce animated GIF output. They are not
    strictly required — fits and PDFs work without them — but 3D
    animations won't render if they're absent.

    Returns the list of missing binary names. Caller decides whether
    to warn (log) or fail (raise).
    """
    missing = []
    if not (shutil.which("mogrify") or shutil.which("magick")):
        missing.append("mogrify")
    if not shutil.which("gifsicle"):
        missing.append("gifsicle")
    return missing
```

Replace with:
```python
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
```

- [ ] **Step 3: Remove unused `shutil` import if no longer used**

```bash
grep -n "shutil\." zunzun/platform_compat.py
```

If the only remaining `shutil` references are inside code we didn't delete, leave the import. If there are no more uses, remove the `import shutil` line from the top of the file.

- [ ] **Step 4: Update `zunzun/apps.py` warning text**

Current content:
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

Replace with:
```python
"""Django app config for zunzun.

Uses AppConfig.ready() to log a startup warning if any required
external binaries are missing from PATH. As of 2026-04-19 the
codebase has no non-Python runtime binary dependencies; the hook
is retained for future platform-specific checks.
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
                "Install the missing binaries via your platform's package manager.",
                ", ".join(missing),
            )
```

- [ ] **Step 5: Delete obsolete tests in `tests/test_platform_compat.py`**

Current obsolete tests (verify with `grep -n "def test_" tests/test_platform_compat.py`):

1. `test_resolve_mogrify_command_prefers_standalone_mogrify` — function deleted.
2. `test_resolve_mogrify_command_falls_back_to_magick` — function deleted.
3. `test_resolve_mogrify_command_raises_when_neither_present` — function deleted.
4. `test_ensure_external_binaries_accepts_imagemagick_7_magick_alone` — binary-specific logic gone.
5. `test_ensure_external_binaries_flags_mogrify_when_neither_imagemagick_available` — binary-specific logic gone.

Delete each of these 5 test functions from `tests/test_platform_compat.py`. Leave surrounding blank lines and module-level docstrings alone.

- [ ] **Step 6: Rewrite the two remaining `ensure_external_binaries` tests**

Find `test_ensure_external_binaries_returns_missing` and `test_ensure_external_binaries_returns_empty_when_all_present`. The function's new behavior returns `[]` unconditionally. Replace both with a single test:

```python
def test_ensure_external_binaries_returns_empty_list():
    """Post-2026-04-19: no runtime binary deps exist; the hook always returns []."""
    assert platform_compat.ensure_external_binaries() == []
```

Keep the original `test_remove_files_matching_*` tests (function retained per spec §5.2).

Keep all `test_run_tool_*` tests (function retained).

- [ ] **Step 7: Run full pytest suite**

```bash
UV_LINK_MODE=copy uv run pytest tests/ -v 2>&1 | tail -10
```

Expected: 79 passed (82 original − 3 resolve_mogrify tests − 2 ensure_external specific tests + 1 rewritten ensure_external test replacing 2 = 82 − 4 = 78, plus 2 new animation tests = 80). Count precisely: original 82, minus 3 resolve_mogrify, minus 1 test_ensure_external_binaries_accepts_imagemagick_7_magick_alone, minus 1 test_ensure_external_binaries_flags_mogrify_when_neither_imagemagick_available, minus 1 of the two ensure_external_returns tests (we collapse to one), plus 2 animation tests = 82 − 5 + 2 = 79.

If the count differs from 79, check whether any parametrization was at play — verify with `grep -c "^def test_" tests/test_platform_compat.py` on before/after to confirm the 5-test delta.

- [ ] **Step 8: Commit**

```bash
git add zunzun/platform_compat.py zunzun/apps.py tests/test_platform_compat.py
git commit -m "$(cat <<'EOF'
Remove mogrify/gifsicle dead code + obsolete tests

- Delete platform_compat.resolve_mogrify_command (no callers).
- Reduce platform_compat.ensure_external_binaries to a stub that
  returns []; the function's scaffolding is retained for future
  platform-specific binary checks.
- Strip imagemagick/gifsicle install instructions from apps.py
  startup warning; the warning infrastructure remains generic.
- Delete 5 obsolete tests (3 resolve_mogrify_* + 2 binary-specific
  ensure_external_binaries_*). Collapse the 2 remaining
  ensure_external tests into one that asserts return == [].

No runtime behavior change: ScatterAnimation and SurfaceAnimation
already moved to matplotlib.PillowWriter in earlier commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 5 — pyproject.toml + documentation

## Task 6: Add Pillow dep and update prose docs

**Files:**
- Modify: `pyproject.toml`
- Modify: `CLAUDE.md`
- Modify: `README.txt`
- Modify: `docs/deployment/linux.md`
- Modify: `docs/deployment/macos.md`
- Modify: `docs/deployment/windows.md`

- [ ] **Step 1: Add `pillow` to pyproject.toml runtime deps**

In `pyproject.toml`, the runtime `dependencies` list currently includes `numpy>=2.0`, `scipy`, `matplotlib>=3.2`, etc. Add `"pillow"` alphabetically between `numpy>=2.0` and `psutil`:

```toml
    # numpy 2.x strict comparison semantics...
    "numpy>=2.0",
    "scipy",
    # matplotlib 3.2 removed the `normed=` kwarg...
    "matplotlib>=3.2",
    "reportlab",
    # Pillow powers matplotlib.animation.PillowWriter, which is used
    # directly by ScatterAnimation / SurfaceAnimation for 3D animated
    # GIF output. Pillow is also a transitive matplotlib dep; declaring
    # it explicitly documents the direct dependency.
    "pillow",
    "psutil",
```

- [ ] **Step 2: Sync and verify**

```bash
UV_LINK_MODE=copy uv sync 2>&1 | tail -5
```

Expected: "Resolved N packages" with no install/remove activity. Pillow is already present; making the dep explicit doesn't install anything new.

```bash
UV_LINK_MODE=copy uv run python manage.py check
```

Expected: clean.

- [ ] **Step 3: Update CLAUDE.md "System dependencies" paragraph**

Find this line in `CLAUDE.md`:
```markdown
**System dependencies** (not Python packages, not managed by uv): `imagemagick` and `gifsicle`. See `README.txt`.
```

Replace with:
```markdown
**No non-Python runtime deps.** Earlier versions required `imagemagick` and `gifsicle` system binaries for animated GIF output; as of 2026-04-19 those paths are pure-Python via matplotlib's `PillowWriter`. See `docs/superpowers/specs/2026-04-19-pillow-gif-design.md` for the migration history.
```

- [ ] **Step 4: Remove imagemagick/gifsicle block from README.txt**

Current content in `README.txt` (lines 16–19):
```
System dependencies for PDF and GIF output are not Python packages
and must be installed separately. On Debian and Ubuntu:

    apt-get install imagemagick gifsicle
```

Delete all four lines (including the blank line above the apt-get command). The preceding line ("uv sync") should be followed directly by the next preserved block (`"First-time setup creates the session database:"`).

- [ ] **Step 5: Update `docs/deployment/linux.md`**

Find:
```
sudo apt-get install -y python3-venv nginx imagemagick gifsicle
```

Change to:
```
sudo apt-get install -y python3-venv nginx
```

- [ ] **Step 6: Update `docs/deployment/macos.md`**

Find:
```
brew install python@3.14 nginx imagemagick gifsicle
```

Change to:
```
brew install python@3.14 nginx
```

- [ ] **Step 7: Update `docs/deployment/windows.md`**

Find any reference to imagemagick or gifsicle:
```bash
grep -n "imagemagick\|gifsicle\|ImageMagick" docs/deployment/windows.md
```

For each match, remove the reference. Most likely locations: an install-prerequisites section listing `winget install ImageMagick.ImageMagick`. Delete those lines and any text introducing them.

- [ ] **Step 8: Run full pytest**

```bash
UV_LINK_MODE=copy uv run pytest tests/ -v 2>&1 | tail -5
```

Expected: 79 passed (unchanged from Task 5; docs edits don't affect tests).

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock CLAUDE.md README.txt docs/deployment/
git commit -m "$(cat <<'EOF'
Add pillow as explicit dep; remove imagemagick/gifsicle from docs

pyproject.toml: declares pillow as a runtime dep (it was already
installed transitively via matplotlib; the direct dependency is
now honest). No install change (uv sync is a no-op).

CLAUDE.md, README.txt, and the three per-platform deployment docs
no longer list imagemagick or gifsicle as system deps. The repo
now has zero non-Python runtime binary dependencies.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 6 — TODO.md

## Task 7: Add animation smoke coverage entry; cross-reference

**Files:**
- Modify: `TODO.md`

- [ ] **Step 1: Append the new entry to `TODO.md`**

Append to the END of `TODO.md` (after the existing "scipy.odr" entry):

```markdown

## Animation smoke coverage still blocked

**Symptom / exposure.** As of 2026-04-19, `ScatterAnimation` and
`SurfaceAnimation` produce animated GIFs via
`matplotlib.animation.PillowWriter` (previously via mogrify +
gifsicle shellouts — see
`docs/superpowers/specs/2026-04-19-pillow-gif-design.md`). The two
animation classes have pytest coverage in `tests/test_animation.py`,
but no smoke-test coverage exists, because:

1. Both classes require `animationHeight > 0`, which means a 3D
   form submission with `animationSize != "0x0"`.
2. Any 3D smoke scenario currently hits the deadlock documented
   in "3D fit spawn-Pool deadlock on Windows smoke" (above).
3. The 3D CharacterizeData path would be a third scenario not
   currently in smoke — even once the deadlock is fixed, it's an
   additional scenario to add.

**When we hit it.** 2026-04-19, Pillow GIF migration. The unit
tests cover code correctness; what's uncovered is the full end-
to-end pipeline through the spawn child, waitress, matplotlib
rendering inside a subprocess, and the resulting `.gif` file
being served from `temp/`.

**Hypothesis.** The existing animation unit tests catch code
correctness (produces a valid multi-frame GIF from the class's
public API). What they don't exercise: session state plumbing,
reports-and-graphs HTML integration, cross-process pickling of
any state the animation classes consume.

**Where to pick up (once the 3D deadlock fix lands).**
- Add a `characterize_3D` smoke scenario that POSTs 3D sample
  data to `/CharacterizeData/3/` with `animationSize=320x240`.
  After completion, GET the response, extract the
  `ScatterAnimation<uniqueString>.gif` URL, fetch the file, assert
  `PIL.Image.open(fp).n_frames >= 2`.
- Add a `polynomial_quadratic_3D_with_animation` scenario (or
  extend the existing `polynomial_quadratic_3D` when that gets
  added to smoke) to POST `animationSize=320x240`, then fetch
  `SurfaceAnimation<...>.gif` and assert the same.
- Estimated added smoke runtime per scenario: 2–3 min on Windows
  on top of the base 3D fit time.

**Not in scope of the Pillow migration branch.** The migration
delivered pure-Python animated GIF rendering; smoke coverage for
3D paths is blocked on a different TODO item (the spawn-Pool
deadlock), so adding smoke coverage here would depend on
unblocking that first.
```

- [ ] **Step 2: Add cross-reference from the 3D deadlock entry**

Near the top of the "3D fit spawn-Pool deadlock on Windows smoke" section (the first section heading below the intro), add a one-line cross-reference right after the existing `**Symptom.**` paragraph ends. Specifically, find:

```markdown
fine — the deadlock is only reproducible under smoke.
```

Right after that line, add a new line:
```markdown

See also: the "Animation smoke coverage still blocked" entry below, which is gated on this one being resolved first.
```

- [ ] **Step 3: Verify TODO.md renders reasonably**

Manual visual check — `TODO.md` is plain markdown. Open it in any markdown viewer or glance at the raw file; confirm section headings are consistent and the new cross-reference is visible.

- [ ] **Step 4: Commit**

```bash
git add TODO.md
git commit -m "$(cat <<'EOF'
Note animation smoke coverage still blocked in TODO.md

Pillow GIF migration (2026-04-19) gave us unit-test coverage of
both animation classes but no smoke coverage. Adding smoke requires
unblocking the 3D-fit-spawn-Pool-deadlock entry first. Cross-
references added both ways.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 7 — Manual visual QA (user)

## Task 8: User verifies animated GIF appearance on the live site

**Files:**
- None — manual QA by the user

This task is performed by the human user. The subagent executing the plan does NOT perform Task 8; instead, the subagent surfaces a clear "ready for manual QA" status after Task 7 commits.

- [ ] **Step 1: Start the site under runserver**

From inside the worktree (`C:\Dropbox\git\zunzunsite3-pillow-gif\`):
```bash
UV_LINK_MODE=copy uv run python manage.py runserver
```

- [ ] **Step 2: Open browser to http://127.0.0.1:8000/**

- [ ] **Step 3: POST a 3D CharacterizeData with animation**

Navigate to CharacterizeData, choose 3D, submit with `animationSize=320x240` and a dataset that has enough 3D variety (or use the default 3D sample data). Wait for the status page to redirect to results.

- [ ] **Step 4: Verify `ScatterAnimation` GIF**

Locate the animated GIF section in the result page. Click to view full-size. Observe for ~15 seconds:
- Does the animation rotate smoothly?
- Are there obvious color-banding artifacts?
- Is the playback speed reasonable (not dizzying-fast, not glacial)?

If any of these fail, abort merge and report back; the spec's color-quantization or fps choices need tuning.

- [ ] **Step 5: POST a 3D fit with animation**

Navigate to FitEquation, choose 3D Polynomial Full Quadratic, submit with `animationSize=320x240` and the default 3D sample data. Wait for completion.

- [ ] **Step 6: Verify `SurfaceAnimation` GIF**

Same visual checks as Step 4.

- [ ] **Step 7: User sign-off**

If both animations look correct, proceed to Phase 8. If any look wrong (wrong speed, wrong colors, obvious artifacts), diagnose before merge.

No commit in Task 8.

---

# Phase 8 — Merge

## Task 9: Local merge to master

**Files:**
- None — git operations

- [ ] **Step 1: Switch to the main checkout**

```bash
cd C:/Dropbox/git/zunzunsite3
```

- [ ] **Step 2: Verify main checkout state**

```bash
git status --short
git branch --show-current
```

Expected: clean working tree on `master`. Ignore untracked `.claude/scheduled_tasks.lock` if present.

- [ ] **Step 3: Merge with `--no-ff`**

```bash
git merge --no-ff pillow-gif-migration -m "$(cat <<'EOF'
Merge Pillow GIF animation migration branch

See docs/superpowers/specs/2026-04-19-pillow-gif-design.md
and docs/superpowers/plans/2026-04-19-pillow-gif-migration.md.

Key changes:
- ScatterAnimation + SurfaceAnimation now use matplotlib's
  FuncAnimation + PillowWriter (zero shellouts, zero temp files).
- platform_compat.resolve_mogrify_command deleted.
- platform_compat.ensure_external_binaries reduced to a stub.
- apps.py startup warning is now generic.
- pillow declared as explicit runtime dep.
- imagemagick and gifsicle removed from all current-state docs
  (CLAUDE.md, README.txt, docs/deployment/*.md).
- Two new pytest unit tests for animation correctness.
- 79 pytest tests pass (was 82; net -3 from mogrify-specific
  test removal).

Repo now has zero non-Python runtime binary dependencies.
Animation smoke coverage remains blocked on the 3D deadlock
TODO (see TODO.md).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Sync main-checkout venv**

Main checkout's `.venv` needs to see the new `pillow` pin (though Pillow is already installed transitively — this is belt-and-suspenders):

```bash
UV_LINK_MODE=copy uv sync 2>&1 | tail -5
```

Expected: "Resolved N packages" — no change (pillow already in `uv.lock` from Phase 5).

- [ ] **Step 5: Final verification on master**

```bash
UV_LINK_MODE=copy uv run python manage.py check
UV_LINK_MODE=copy uv run pytest tests/ -v 2>&1 | tail -5
UV_LINK_MODE=copy uv run python -c "import PIL; print(f'Pillow {PIL.__version__}')"
```

Expected:
- check: `System check identified no issues (0 silenced).`
- pytest: `79 passed`
- PIL: `Pillow 12.2.0` (or later)

- [ ] **Step 6: Do NOT push**

Do NOT run `git push`. The user has explicitly stated local merge is the desired endpoint; pushing to `origin` requires explicit user approval.

- [ ] **Step 7 (optional): Clean up the worktree**

```bash
git worktree remove ../zunzunsite3-pillow-gif
git branch -d pillow-gif-migration
```

Leave in place if the user wants to poke at the branch. User preference from prior migrations was to leave the worktree.

---

## Self-review checklist (plan author runs this before handoff)

**1. Spec coverage:** Every spec section has at least one task:

- Spec §1 (deliverables) → Tasks 2–7 (tests, refactors, platform_compat, pyproject, docs, TODO).
- Spec §2 (constraints) → Global conventions (UV_LINK_MODE=copy, migrate note).
- Spec §3 (decisions) → Tasks honor all 8: FuncAnimation+PillowWriter (Tasks 3–4), explicit pillow dep (Task 6), no floor (Task 6), unit test + manual QA (Tasks 2, 8), delete resolve_mogrify_command (Task 5), prune ensure_external_binaries (Task 5), worktree+phased commits (all tasks), no push (Task 9).
- Spec §4 (architecture) → Tasks 3–4 implement the new lifecycle.
- Spec §5.1 (ReportsAndGraphs.py rewrites) → Tasks 3–4.
- Spec §5.2 (platform_compat) → Task 5 Steps 1–3.
- Spec §5.3 (apps.py) → Task 5 Step 4.
- Spec §5.4 (pyproject.toml) → Task 6 Step 1.
- Spec §5.5 (tests/test_animation.py) → Task 2.
- Spec §5.6 (CLAUDE.md) → Task 6 Step 3.
- Spec §5.7 (README.txt) → Task 6 Step 4.
- Spec §5.8 (deployment docs) → Task 6 Steps 5–7.
- Spec §5.9 (TODO.md) → Task 7.
- Spec §6 (phases) → Phases 0–8 map 1:1.
- Spec §7 (risks) → Task 2 Step 3 (test-first gate catches PillowWriter API surprises); Task 3 Step 3 (closure bug detection); Task 8 (manual QA gates color-quantization + fps).
- Spec §8 (acceptance criteria) → Task 9 Step 5 final verification.

**2. Placeholder scan:** No "TBD", "implement later", "similar to Task N", or unresolved promises. All code blocks are literal.

**3. Type consistency:** `FuncAnimation`, `PillowWriter`, `ScatterAnimation`, `SurfaceAnimation`, `_update` are named consistently across Tasks 2–4. `ensure_external_binaries` signature (returns `list[str]`) is consistent in Task 5.
