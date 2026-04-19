# Replace mogrify + gifsicle with matplotlib PillowWriter — Design

**Date:** 2026-04-19
**Branch (planned):** `pillow-gif-migration` in worktree `../zunzunsite3-pillow-gif/`
**Status:** Brainstorm complete, awaiting user sign-off before plan.

## 1. Scope & Goals

Drop the two external binary dependencies (ImageMagick's `mogrify` / `magick` and `gifsicle`) entirely by replacing the current "savefig PNG → mogrify PNG→GIF → gifsicle concat" pipeline in both `ScatterAnimation` and `SurfaceAnimation` with `matplotlib.animation.FuncAnimation` + `matplotlib.animation.PillowWriter`. Animated GIF output becomes pure-Python.

**Deliverables:**

- `ScatterAnimation.CreateCharacterizerOutput` and `SurfaceAnimation.CreateReportOutput` (both in `zunzun/LongRunningProcess/ReportsAndGraphs.py`) rewritten to use `FuncAnimation` + `PillowWriter`.
- `platform_compat.resolve_mogrify_command` deleted.
- `platform_compat.ensure_external_binaries` no longer inspects `mogrify`, `magick`, or `gifsicle`.
- `zunzun/apps.py` startup warning no longer mentions imagemagick or gifsicle installation instructions.
- `pillow` declared as an explicit runtime dep in `pyproject.toml`.
- `tests/test_animation.py` (new) asserts both animation classes produce valid multi-frame GIFs.
- `README.txt`, `CLAUDE.md`, and `docs/deployment/*.md` no longer list imagemagick or gifsicle as system deps.
- `TODO.md` gets a new entry flagging that animation smoke scenarios remain out of reach until the 3D deadlock is resolved.

**Non-goals:**

- No change to frame count, rotation step, or per-axis rotation math.
- No change to the `animationSize` form field or the `animationHeight == 0` short-circuit.
- No fix for the 3D deadlock documented in `TODO.md` — this migration is upstream of that.
- No push to `origin` (user preference — same as previous migrations).

## 2. Constraints & Context

- Pillow 12.2.0 is already installed transitively via matplotlib; `features.check('libjpeg_turbo')` returns `True` and animated-GIF output is a long-stable Pillow feature.
- Both animation paths are 3D-only (`animationHeight == 0` short-circuits on 2D) and opt-in via the `animationSize` form field, whose default is `"0x0"`.
- Neither animation class is currently exercised by the smoke test (scenarios set `animationSize="0x0"`) nor by any pytest test.
- The 3D deadlock TODO (`TODO.md`) blocks any smoke scenario that would POST a 3D fit, so animation smoke coverage is unreachable by the current test harness regardless of this migration.
- `platform_compat.run_tool` and `platform_compat.remove_files_matching` have other callers and must stay.
- Ambient environment constraint: Dropbox filesystem requires `UV_LINK_MODE=copy` on every `uv` invocation.

## 3. Decisions (Locked In)

| # | Decision | Alternatives considered |
|---|---|---|
| 1 | **Use `matplotlib.animation.FuncAnimation` + `PillowWriter`** | Direct per-frame PIL Image collection; minimal-diff replacement of the two shellouts with PIL calls only |
| 2 | **Declare `pillow` explicitly in `pyproject.toml` runtime deps** | Keep as transitive via matplotlib |
| 3 | **No `>=` floor on Pillow** | Pin to current version or a named floor |
| 4 | **Unit test (`tests/test_animation.py`) plus user's manual visual QA** | Unit test only; manual QA only; smoke-based testing |
| 5 | **Delete `resolve_mogrify_command` entirely** | Leave it deprecated but present |
| 6 | **Prune mogrify + gifsicle from `ensure_external_binaries`** but keep the function; it may still guard future binaries | Delete the function entirely |
| 7 | **Single worktree + phased commits, same pattern as prior migrations** | One large commit; multiple branches |
| 8 | **Local merge only; no push** | Push to origin |

## 4. Architecture

### 4.1 Current animation lifecycle

For each of the two 3D animation classes:

1. `CreateReportOutput()` (or `CreateCharacterizerOutput`) called inside a try/except.
2. matplotlib 3D figure constructed via `eval(self.functionString + "(self.dataObject, None)")`.
3. `for i in range(0, 360, self.animationFrameSeparation):`
   - `ax.view_init(elev=self.dataObject.altimuth3D, azim=i)`
   - `fig.savefig(frameName, format="png")` — write one temp PNG
   - `platform_compat.run_tool(resolve_mogrify_command(), ["-format", "gif", frameName])` — shell out per frame, write sibling GIF
4. `platform_compat.run_tool("gifsicle", ["--colors", "256", "--loopcount", *sorted_gif_frames], stdout_file=final_path)` — shell out once, write final animated GIF.
5. `platform_compat.remove_files_matching(temp_glob)` — delete all PNG and GIF frame files.

Per animation: ~36 matplotlib saves + ~36 mogrify shellouts + 1 gifsicle shellout + ~72 temp files created and deleted.

### 4.2 New animation lifecycle

Same two classes, rewritten:

1. `CreateReportOutput()` called inside a try/except (unchanged).
2. matplotlib 3D figure constructed (unchanged).
3. `def _update(frame):` — closure over `ax` and `self.dataObject.altimuth3D`; calls `ax.view_init(elev=self.dataObject.altimuth3D, azim=frame)`. Return value is not used when `blit=False`.
4. `anim = FuncAnimation(fig, _update, frames=range(0, 360, self.animationFrameSeparation), blit=False)`
5. `anim.save(self.physicalFileLocation, writer=PillowWriter(fps=10))`
6. `plt.close("all")` (preserved for memory release).

Per animation: 1 `FuncAnimation` construction + 1 `.save()` call. Zero subprocesses, zero temp files.

### 4.3 Why `FuncAnimation` + `PillowWriter`

- Uses matplotlib's own animation abstraction — no hand-rolled frame collection.
- `PillowWriter` delegates GIF encoding to Pillow's animated-GIF writer, which is pure-Python and well-tested.
- `blit=False` is the correct choice for 3D axes (which don't support partial redraws cleanly). No performance loss vs. the current explicit loop — `view_init` changes require a full redraw either way.
- `fps=10` yields ~100 ms per frame, matching what browsers render today (most browsers floor GIF frame delays at 100 ms regardless of what mogrify/gifsicle wrote).

### 4.4 Color quantization note

All replacements (not just option A) switch from ImageMagick's color quantization to Pillow's median-cut-with-dithering. On matplotlib's smooth 3D colormaps this is typically imperceptible. User's manual visual QA is the acceptance gate for this aesthetic parity; unit tests do not attempt to compare output pixels to a golden.

## 5. Components Touched

### 5.1 `zunzun/LongRunningProcess/ReportsAndGraphs.py`

Both `ScatterAnimation.CreateCharacterizerOutput` (lines ~1492–1531) and `SurfaceAnimation.CreateReportOutput` (lines ~1559–1599) rewritten per §4.2. The `for i in range(0, 360, ...)` loop, the `frameName` / `padstr` bookkeeping, both `platform_compat.run_tool` calls, the glob + sort, and `platform_compat.remove_files_matching` all go away per animation class. New import: `from matplotlib.animation import FuncAnimation, PillowWriter`.

The `platform_compat` import stays at the top of the file; `run_tool` and `remove_files_matching` remain used by other callers in the same file (audit in Phase 0 to confirm).

### 5.2 `zunzun/platform_compat.py`

- Delete the `resolve_mogrify_command` function (lines ~176–200 including docstring).
- In `ensure_external_binaries`, remove the mogrify-presence check and the gifsicle-presence check. If the function now has no remaining checks, reduce to a body that returns an empty list; document that it's retained as a hook for future binary checks.

### 5.3 `zunzun/apps.py`

The `AppConfig.ready()` warning currently reads "...missing external binaries on PATH: %s. Fits will work, but animated GIF output will fail. Install with: apt-get install imagemagick gifsicle ...". Since mogrify+gifsicle are the only external binaries the code depends on, `ensure_external_binaries()` will return an empty list in all real deployments post-migration and the warning never fires. Options: (a) keep the AppConfig.ready() hook as-is with the now-dead-code path, (b) remove the AppConfig entirely, (c) rewrite the warning message to be generic ("install missing binaries"). Decision: **(a)** — keep the hook, remove the imagemagick/gifsicle-specific text from the warning message. This leaves the infrastructure in place for future binary checks without stranding dead code today.

### 5.4 `pyproject.toml`

Add `"pillow"` to the runtime `dependencies` list, alphabetically between `numpy` and `psutil`. No version floor.

### 5.5 `tests/test_animation.py` (new)

Two test functions (separate because target classes differ; not parametrized):

- `test_scatter_animation_produces_gif` — builds a `DataObject` stub with `dimensionality=3`, `animationHeight=240`, `animationWidth=320`, `altimuth3D=20`, plus 3D sample data from `DefaultData.defaultData3D`. Instantiates `ScatterAnimation`, calls `PrepareForCharacterizerOutput()` to set `physicalFileLocation`, calls `CreateCharacterizerOutput()`, asserts the output path exists and `PIL.Image.open(path).n_frames >= 2`.
- `test_surface_animation_produces_gif` — same shape, but for `SurfaceAnimation.CreateReportOutput`. Requires the DataObject's equation to have solved coefficients, so the stub sets `equation.solvedCoefficients` directly to known values for a 3D `Linear` polynomial rather than running a live fit.

Both tests run without `@pytest.mark.django_db` — no server, no spawn, no session DB. Expected runtime: 3–8 s each on modern hardware. Framework: pytest + pytest-django (for settings module only).

### 5.6 `CLAUDE.md`

The "System dependencies" paragraph currently reads:

```
**System dependencies** (not Python packages, not managed by uv): `imagemagick` and `gifsicle`. See `README.txt`.
```

Replace with:

```
**No non-Python runtime deps.** Earlier versions required `imagemagick` and `gifsicle` system binaries for animated GIF output; as of 2026-04-19 those paths are pure-Python via matplotlib's `PillowWriter`. See `docs/superpowers/specs/2026-04-19-pillow-gif-design.md` for the migration history.
```

### 5.7 `README.txt`

Lines 16–19 currently read:

```
System dependencies for PDF and GIF output are not Python packages
and must be installed separately. On Debian and Ubuntu:

    apt-get install imagemagick gifsicle
```

Delete the entire block. Nothing replaces it — after this migration, the repo has zero non-Python runtime system deps, and the PDF-generation path uses reportlab + lxml + bs4, all pure-Python and managed by uv.

### 5.8 `docs/deployment/linux.md`, `docs/deployment/macos.md`, `docs/deployment/windows.md`

Each has a per-platform install command. Strike `imagemagick` and `gifsicle` from the apt-get / brew / winget lines. If a command becomes empty (no remaining system deps), collapse or remove the line entirely.

### 5.9 `TODO.md`

Add a new entry: "Animation smoke coverage still blocked". Documents that post-migration, the two animation code paths (`ScatterAnimation`, `SurfaceAnimation`) remain unverified by automated smoke because both require a 3D scenario and the existing 3D deadlock (already tracked) must be resolved first. Includes a pickup-plan sketch: once the deadlock fix lands, two new smoke scenarios (chained to 3D CharacterizeData and chained to `polynomial_quadratic_3D`) are the natural additions, both asserting `PIL.Image.open(gif).n_frames >= 2` on the returned static files.

Also add a cross-reference back from the existing "3D fit spawn-Pool deadlock" entry pointing at this new entry so the two are discoverable together.

## 6. Execution Phases

1. **Phase 0 — Setup.** Create worktree `../zunzunsite3-pillow-gif/` with branch `pillow-gif-migration` off master. Baseline: 82 pytest + 8-scenario smoke green on current code. Audit `ReportsAndGraphs.py` for other `platform_compat` call sites to confirm `run_tool` / `remove_files_matching` stay load-bearing.
2. **Phase 1 — Unit tests first (TDD gate).** Create `tests/test_animation.py` with both tests against the *current* mogrify+gifsicle implementation. Both pass — proves the test shape is right before we touch the code under test.
3. **Phase 2 — Refactor `ScatterAnimation`.** Rewrite `CreateCharacterizerOutput` to use `FuncAnimation` + `PillowWriter`. `test_scatter_animation_produces_gif` continues to pass. Commit.
4. **Phase 3 — Refactor `SurfaceAnimation`.** Same shape rewrite for `CreateReportOutput`. `test_surface_animation_produces_gif` continues to pass. Commit.
5. **Phase 4 — Prune platform_compat + apps.py.** Delete `resolve_mogrify_command`; simplify `ensure_external_binaries`; rewrite the `apps.py` warning text. Commit.
6. **Phase 5 — pyproject.toml + docs.** Add `pillow`; `uv sync` (no change expected since already installed transitively); update `CLAUDE.md`, `README.txt`, the three deployment docs. Commit.
7. **Phase 6 — TODO.md.** Add the "animation smoke coverage" entry; cross-link from the 3D deadlock entry. Commit.
8. **Phase 7 — Manual visual QA (user).** User runs the site locally, POSTs a 3D fit with `animationSize=320x240`, verifies animated GIF rotates smoothly with no obvious regressions. User signs off.
9. **Phase 8 — Merge.** Local `git merge --no-ff pillow-gif-migration` on master from the main checkout. Do NOT push.

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| `PillowWriter` API subtly different on matplotlib 3.10.8 than docs suggest. | Phase 1 unit tests exercise it directly; Phase 2/3 rewrites tested against it. No later surprise. |
| `ax.view_init` inside `FuncAnimation` doesn't drive a redraw. | Unit test asserts `n_frames >= 2`; if all frames are identical, the Pillow writer would still report multiple frames but visually they'd be static — manual QA catches this. As a belt-and-suspenders, a stricter assertion can compare frame hashes. |
| Color quantization visibly worse than ImageMagick's. | Manual QA gate (§5.5 and phase 7). Fallback if it matters: configure `PillowWriter` with a custom palette, or round-trip frames through explicit `Image.quantize(...)`. Not expected to trigger. |
| Frame rate wrong. | `fps=10` matches today's browser-floored playback. Manual QA verifies; tuning is a one-line change. |
| DataObject stub in unit tests can't satisfy animation classes' attribute reads. | Iterate: run test, add missing attribute to stub, run again. Budget a few iterations. |
| `platform_compat.ensure_external_binaries()` breaks because it's called by `apps.py` but no longer has meaningful work. | Keep the function skeleton intact (§5.2, §5.3). AppConfig.ready() behavior unchanged; function just returns `[]` in all deployments. |
| pyeq3 or matplotlib release between now and plan execution changes Pillow interaction. | Unlikely in days-scale timeframe; lockfile pins current state. |

## 8. Acceptance Criteria

- `grep -rn "mogrify\|gifsicle\|resolve_mogrify_command\|run_tool.*mogrify\|run_tool.*gifsicle" zunzun/ tests/` returns only matches inside `docs/` (historical specs) or `uv.lock` (never runtime code).
- `UV_LINK_MODE=copy uv run python manage.py check` clean.
- `UV_LINK_MODE=copy uv run pytest tests/ -v` passes 84 tests (82 existing + 2 new).
- `UV_LINK_MODE=copy uv run python scripts/smoke_test.py` passes all 8 scenarios (unchanged; no new animation scenarios yet per the TODO.md note).
- `pyproject.toml` lists `pillow` under runtime deps.
- `CLAUDE.md`, `README.txt`, and all three `docs/deployment/*.md` files no longer reference imagemagick or gifsicle.
- `TODO.md` has a new "Animation smoke coverage" entry and a cross-reference from the existing 3D deadlock entry.
- User's manual visual QA on 3D animated GIFs passes.
- Site runs under both `runserver` and `waitress-serve`.
