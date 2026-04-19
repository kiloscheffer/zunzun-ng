# TODO — known deferred issues

Tracked items that are real defects or loose ends, but are scoped out of the
current branch. Each entry documents the symptom, the hypothesis, what we
*didn't* do, and where to pick up from.

## 3D fit spawn-Pool deadlock on Windows smoke

**Symptom.** When `scripts/smoke_test.py` runs a 3D polynomial-quadratic fit
against a 12-point (X, Y, Z) grid (`/FitEquation__F__/3/Polynomial/Full Quadratic/`),
the smoke harness never sees the final result body. The main waitress-server
python.exe silently stops writing output ~15 matplotlib reports into the fit's
report generation and stays idle for 80+ minutes with 3 zombie spawn-Pool
workers at ~5 MB resident each. Manual click-through on the live server works
fine — the deadlock is only reproducible under smoke.

See also: the "Animation smoke coverage still blocked" entry below, which is gated on this one being resolved first.

Additional 2026-04-19 context: the `MatplotlibGraphs_3D.py` `fig.gca(projection='3d')` bug was fixed in commit `0ac249a` (Phase 1a of the Pillow GIF migration). This fix may partially or wholly resolve the deadlock described above — a silent TypeError during matplotlib 3D figure construction inside a Pool worker would present identically to the described symptom. Worth re-testing the 3D smoke scenario (see plan Task 4 in docs/superpowers/plans/2026-04-18-django-upgrade.md) after this migration lands.

**When we hit it.** 2026-04-18, Phase 1 of the Django 2.2 → 5.2 LTS migration
(plan: `docs/superpowers/plans/2026-04-18-django-upgrade.md`, Task 4).

**Hypothesis.** A spawn-Pool worker dies silently during matplotlib report
rendering (OOM? import race? ImageMagick `magick mogrify` shellout hang?).
The parent's `pool.map_async(...).get()` blocks forever because spawn on
Windows has no equivalent of SIGCHLD — a dead child is indistinguishable from
a slow child. 2D fits generate ~4 reports per run; 3D generates ~15. Exposure
probability scales with report count, which is why 2D smoke has been stable
across dozens of runs and 3D tripped immediately.

**What we did instead.** Dropped the `polynomial_quadratic_3D` scenario from
the smoke test. The final smoke suite has 8 scenarios (was planned to be 9).
This preserves the migration's test-expansion intent for every other path but
leaves 3D coverage as a known hole.

**Where to pick up.**
- Reproduce: uncomment the `_DATA_3D_POLY` / `_POLY_QUAD_3D_FIELDS` / scenario
  block from the plan's Task 4 and run `uv run python scripts/smoke_test.py`.
  Budget ≥30 min; deadlock currently happens around the 15th `.png` written
  to `temp/`.
- Diagnose options (pick one):
  1. Instrument `CreateOutputReportsInParallelUsingProcessPool` in
     `StatusMonitoredLongRunningProcessPage.py` to log per-worker lifecycle
     events (enter / exit / exception); rerun the 3D smoke and see which
     worker doesn't emit an exit event.
  2. Replace `multiprocessing.Pool` with `concurrent.futures.ProcessPoolExecutor`
     which surfaces child exceptions on `.result()` rather than swallowing them.
  3. Add a per-worker wall-clock timeout wrapper; if a worker exceeds N seconds,
     force-kill and fail the fit rather than hanging.
- Fix (TBD — depends on diagnosis). Likely a small pyeq3/matplotlib interaction
  patch or a pool-wrapper change in the LRP base class. Unrelated to anything
  else in the Django migration.

**Not in scope of the Django 5.2 branch.** Fixing this deserves its own
branch and its own spec/plan cycle, since the root cause is in the
spawn-Pool pattern (shared with the cross-platform migration), not in
Django version compatibility.

## Spline + UDF session round-trip not smoke-covered

**Symptom / exposure.** Phase 3 of the Django 5.2 migration introduced
`_json_native` at all `SaveSpecificDataToSessionStore` sites in the LRP
subclass tree, which converts numpy arrays to plain Python lists before
the session write. Two specific shapes land in session data but aren't
exercised end-to-end by smoke:

1. **`FitSpline.scipySpline` is a tuple `(knots_ndarray, coefs_ndarray, degree_int)`.**
   After `_json_native`, this becomes `[list_of_floats, list_of_floats, int]`.
   `EvaluateAtAPointView` reads it back via `LoadItemFromSessionStore` and
   assigns to `equation.scipySpline`. scipy's `BSpline` / `splev` functions
   accept tuple-of-arrays but may raise on list-of-lists. There is no smoke
   scenario for spline fits — `scripts/smoke_test.py` does not POST to any
   `/FitEquation__F__/[23]/Spline/...` URL.

2. **`FitUserDefinedFunction.solvedCoefficients`** stores a numpy array
   which is now cast to a list at write time. `EvaluateAtAPointView`
   converts back via `numpy.array(...)` when loading, so this one is
   likely fine — but no smoke scenario exercises UDF end-to-end, so the
   claim is unverified.

**When we hit it.** 2026-04-18, Phase 3 refactor. `_json_native` was
applied defensively across all Fit* subclasses because numpy → JSON
would crash at runtime otherwise. Smoke coverage for these paths was
out of scope for the Django 5.2 branch.

**Hypothesis.** The spline case is the real risk. scipy's BSpline
constructors are historically strict about array-vs-list types. A user
who completes a spline fit and then clicks Evaluate-at-a-Point may get
a TypeError.

**Where to pick up.**
- Add a `spline_2D` smoke scenario: POST to `/FitEquation__F__/2/Spline/...`
  with a suitable equation + dataset, chain Evaluate-at-a-Point after it
  the same way `evaluate_at_a_point` chains after `polynomial_quadratic_2D`.
- Add a `udf_2D` smoke scenario: POST to `/FitUserDefinedFunction__F__/2/`
  with a simple formula like `a + b*X`, chain evaluation.
- If either fails with a scipy type error, the fix is at the load site
  (`EvaluateAtAPointView`): after `LoadItemFromSessionStore(...)`, cast
  back to the right scipy-accepted shape before assigning.

**Not in scope of the Django 5.2 branch.** The 5.2 branch delivered its
intended surface; these two scenarios are low-frequency user paths and
exercising them is future work.

## pyeq3 imports `scipy.odr` which scipy 1.19.0 will remove

**Symptom.** Every `pytest` run and every smoke run emits:

```
.venv/Lib/site-packages/pyeq3/Services/SolverService.py:19:
DeprecationWarning: `scipy.odr` is deprecated as of version 1.17.0
and will be removed in SciPy 1.19.0. Please use
`https://pypi.org/project/odrpack/` instead.
    import scipy.odr
```

When scipy 1.19.0 ships and `uv sync` picks it up, `import pyeq3` will
fail at module-import time with `ModuleNotFoundError: No module named
'scipy.odr'`. Every view that touches a fit path crashes; the smoke test
dies at scenario 1.

**When we hit it.** The warning was present before both the Django 5.2
and Django 6.0 migrations — pre-existing, not introduced by either
upgrade. Expected hard break: ~late 2026 / early 2027 when scipy 1.19
ships.

**Hypothesis.** pyeq3 12.6.1 uses `scipy.odr` for orthogonal distance
regression (ODR fitting — one of the fit-target options exposed in the
"fittingTarget" form field). scipy moved the canonical implementation
out to a standalone `odrpack` package on PyPI. pyeq3 maintenance has
been dormant since the Python 3.10 era (classifiers top out at 3.10,
though the code itself works on 3.11–3.14 empirically).

**Where to pick up.**
- Monitor scipy releases. The warning moves to `ImportWarning` or the
  module is removed entirely when 1.19.0 lands.
- Fix options (pick one, in order of preference):
  1. **Upstream patch.** Fork pyeq3, replace `import scipy.odr` with
     `import odrpack as odr` (and update any `scipy.odr.X` references
     accordingly), submit PR or pin to the fork.
  2. **Vendor patch.** Apply a small local patch to
     `.venv/Lib/site-packages/pyeq3/Services/SolverService.py`
     post-install via a uv hook or a pyproject.toml `[tool.uv.sources]`
     override pointing at a patched fork.
  3. **Pin scipy below 1.19.** Add `"scipy<1.19"` to
     `pyproject.toml`'s dependency list. Simplest and works
     indefinitely, but loses future scipy improvements.
- Verification: smoke test exercises the fit path through pyeq3
  end-to-end; if it passes post-fix, the ODR code path is healthy.
  FunctionFinder's Exponential family smoke scenario implicitly
  exercises nonlinear fitting via differential evolution, which is the
  path most likely to touch the deprecated module.

**Not in scope of either Django migration.** The Django upgrades were
pin bumps that left pyeq3 untouched. Fixing the scipy coupling
requires a pyeq3-side change, which deserves its own branch — small
enough that it doesn't need a full spec, but disruptive enough to
warrant isolated commits.

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
