# TODO — known deferred issues

Tracked items that are real defects or loose ends, but are scoped out of the
current branch. Each entry documents the symptom, the hypothesis, what we
*didn't* do, and where to pick up from.

## ~~3D fit spawn-Pool deadlock on Windows smoke~~ RESOLVED 2026-04-19

> **Resolution.** There was no deadlock. The 3D POST was returning an
> HTTP 200 error-form response (`Error In Form: The selected model has
> more coefficients than distinct independent data values`) because the
> test dataset had X ∈ {1,2,3,4} and Y ∈ {1,2,3} — overlapping ranges
> whose union is only 4 distinct values, less than the 6 coefficients
> of a 3D Full Quadratic. `Equation_3D.clean()` rejected the form
> instantly. The smoke harness then polled `/StatusAndResults/`
> watching for REFRESH/REDIRECT to disappear, but the status session
> still held the PREVIOUS scenario's (completed) `characterize_2D`
> state which kept rendering the REFRESH meta tag, so the polling
> loop never terminated and hit the 1800s scenario timeout.
>
> Fixed in `scripts/smoke_test.py` by using non-overlapping X ∈ {1,2,3,4}
> and Y ∈ {5,6,7} (7 distinct values union). The scenario now completes
> in ~5 s. `polynomial_quadratic_3D` is scenario 6 of 9 in smoke.
>
> The `MatplotlibGraphs_3D.py` `fig.gca(projection='3d')` bug fixed in
> commit `0ac249a` (Phase 1a of the Pillow GIF migration) was a
> genuine adjacent bug, also affecting 3D rendering but via a
> completely different mechanism (silent try/except swallowing at the
> live site's report-generation path). Both bugs manifested as
> "3D broken on Windows" but were unrelated in code and symptom.
>
> Historical investigation notes below, preserved for reference.

**Symptom (original, now understood to be measurement artifact).**
When `scripts/smoke_test.py` runs a 3D polynomial-quadratic fit
against a 12-point (X, Y, Z) grid (`/FitEquation__F__/3/Polynomial/Full Quadratic/`),
the smoke harness never sees the final result body. The main waitress-server
python.exe silently stops writing output ~15 matplotlib reports into the fit's
report generation and stays idle for 80+ minutes with 3 zombie spawn-Pool
workers at ~5 MB resident each. Manual click-through on the live server works
fine — the deadlock is only reproducible under smoke.

The "~15 matplotlib reports" and "~60 matplotlib reports" counts were
conflated across scenarios: those PNGs came from the 2D/FunctionFinder
scenarios that ran BEFORE the 3D POST in the same smoke session. No 3D
worker actually ran, because form validation rejected the POST before
any spawn.

See also: the "Animation smoke coverage still blocked" entry below, which is gated on this one being resolved first.

**2026-04-19 re-test result (partial progress, deadlock still present):**
Post-Pillow migration (which landed commit `0ac249a` fixing
`MatplotlibGraphs_3D.py`'s `fig.gca(projection='3d')`), the 3D
smoke scenario was re-added and run. **The matplotlib fix was
necessary but not sufficient.** Observations:

- Before the fix: main python.exe silent after **~15 PNGs** written to `temp/`.
- After the fix: main python.exe silent after **~60 PNGs** (PID 4816 generated 60 files, visible via `ls temp/*.png | grep -oE '_[0-9]+_' | sort | uniq -c`).
- Progress is ~4x deeper into the report-generation pipeline than before, but still hangs.
- **No `temp/{pid}.log` file produced by the 3D run** (contrast with pre-fix behavior, where mogrify/projection TypeErrors logged). So the worker isn't raising anything Python-visible — it's hanging cleanly.
- **ImageMagick/gifsicle hypothesis is definitively dead.** The Pillow migration removed all mogrify/gifsicle shellouts from the runtime path, yet the deadlock persists. Cause is inside pure-Python matplotlib / multiprocessing.Pool.

Refined hypothesis for next investigator: a `multiprocessing.Pool` task in `CreateOutputReportsInParallelUsingProcessPool` (StatusMonitoredLongRunningProcessPage.py) never returns. Likely one of the heavier 3D report types between PNGs #16 and #60 (3D scatter error plots, surface/contour pairs) hangs inside matplotlib's agg backend on Windows-spawn workers. Instrumenting per-worker lifecycle events (diagnose option 1 below) would identify which report type triggers it.

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

## ~~Spline + UDF session round-trip not smoke-covered~~ RESOLVED 2026-04-20

> **Resolution.** Two smoke scenarios added to `scripts/smoke_test.py`
> and four real bugs shaken out along the way. The smoke suite is now
> at 12 scenarios; all pass.
>
> **New scenarios:**
> - `spline_2D` — 2D cubic spline fit (smoothness=1.0, order=3),
>   chained into `/EvaluateAtAPoint/` to verify the full round-trip.
> - `udf_2D` — 2D User Defined Function fit (`a + b*X`), chained the
>   same way.
>
> **Bugs fixed in the process:**
> 1. **Spline write-site crashed on session save.**
>    `FitSpline.SaveSpecificDataToSessionStore` was storing the live
>    `scipy.interpolate.UnivariateSpline` object through `_json_native`
>    (which doesn't collapse it), so Django's `JSONSerializer` raised
>    `TypeError: Object of type UnivariateSpline is not JSON
>    serializable`. The key was redundant — `solvedCoefficients`
>    already holds the spline's tck tuple. Dropped the key at the
>    write site. `EvaluateAtAPointView` now reconstructs a
>    `scipy.interpolate.BSpline` (2D) or a tiny bisplev wrapper (3D)
>    from the tck at load time.
> 2. **pyeq3 API drift:**
>    `IModel.ParseAndCompileUserFunctionString` gained a required
>    `dim` parameter. Five zunzun callsites still passed one
>    argument, so the UDF POST fell over in form validation with
>    `TypeError: missing 1 required positional argument 'dim'`.
>    Adapted all five callsites (`forms.py` × 2,
>    `FitUserDefinedFunction.py`,
>    `StatusMonitoredLongRunningProcessPage.py`, `views.py`).
> 3. **UDF code object is not picklable.** The parse call caches a
>    `compile()` result on the equation at `.userFunctionCodeObject`,
>    which spawn's `Popen.reduction.dump` choked on when pickling
>    the `ChildPayload`. Stripped the attribute in
>    `build_child_payload` and re-parse in `apply_child_payload` to
>    reconstruct in the child.
> 4. **Read-site cast for non-spline `solvedCoefficients`.** Added a
>    `numpy.array(...)` cast at the shared load line so pyeq3's
>    `CalculateModelPredictions` receives the ndarray shape it
>    expects, independent of future scipy/pyeq3 strictness.
>
> All four bugs were pre-existing latent issues that only surfaced
> once the two smoke scenarios actually exercised the full
> fit + round-trip. Pytest count unchanged at 78/78.
>
> See `docs/superpowers/specs/2026-04-19-spline-udf-smoke-design.md`
> and `docs/superpowers/plans/2026-04-19-spline-udf-smoke.md` for the
> original design and the 2026-04-20 scope-refinement notes.
>
> Historical notes below, preserved for reference.

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

## ~~pyeq3 imports `scipy.odr` which scipy 1.19.0 will remove~~ RESOLVED 2026-04-20

> **Resolution.** Forked `github.com/equations-project/pyeq3`
> (the upstream actually published to PyPI as pyeq3) into
> `github.com/kiloscheffer/pyeq3ng`, ported `pyeq3/IModel.py` and
> `pyeq3/Services/SolverService.py` from `scipy.odr.{Model,Data,ODR}`
> to `odrpack.odr_fit`. Tagged `v1.0.0-ng`. zunzunsite3's
> `pyproject.toml` pins to that tag via `[tool.uv.sources]`.
> The `scipy.odr` DeprecationWarning is gone from both pytest and
> smoke logs.
>
> **Validation:**
> - pyeq3ng's UnitTests: 118 pass / 1 pre-existing fail (UDF Fpv,
>   unrelated to ODR).
> - Captured a one-shot scipy.odr baseline fixture, confirmed ported
>   coefficients match within `rtol=1e-3` across 4 polynomial cases
>   (2D/3D × ODR/SSQABS), then removed the fixture post-merge.
> - zunzunsite3 pytest: 78/78 pass.
> - zunzunsite3 smoke: 12/12 pass.
>
> **Key mapping:** scipy.odr's class-based API (`Model(f_beta_x)` +
> `Data(x, y[, we])` + `ODR(...).run()`) maps to odrpack's
> `odr_fit(f_x_beta, xdata, ydata, beta0=..., weight_y=..., task=...,
> diff_scheme=..., maxit=...)` with a per-callsite closure handling
> the `(beta, x)` → `(x, beta)` arg-order swap. `set_job(fit_type=0,
> deriv=0)` = `task="explicit-ODR", diff_scheme="forward"`;
> `set_job(fit_type=2)` + `maxit=0` (OLS, no iterations — used for
> covariance extraction) = `task="OLS", maxit=1`.
>
> **Fork scope:**
> - `github.com/kiloscheffer/pyeq3ng` is a permanent fork. Upstream
>   (equations-project) has not addressed scipy.odr yet; an earlier
>   iteration of the fork targeted the older `bitbucket.org/zunzuncode/pyeq3`
>   which has been dormant since 2020-01, but was rebased once we
>   discovered PyPI's pyeq3 comes from equations-project.
> - Additional fork-only changes in `pyproject.toml`: numpy upper
>   bound removed (upstream's `^1.24` blocked numpy 2.x),
>   `odrpack>=0.5.0` and `pypandoc>=1.10` added (the latter was
>   undeclared in upstream but imported by `pyeq3.Utilities.Multifit`).
>
> See `docs/superpowers/specs/2026-04-20-pyeq3ng-odr-port-design.md`
> and `docs/superpowers/plans/2026-04-20-pyeq3ng-odr-port.md` for
> the design and execution record.
>
> Historical notes below, preserved for reference.

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

## ~~Animation smoke coverage still blocked~~ RESOLVED 2026-04-19

> **Resolution.** The blocking dependency on the 3D fit "deadlock"
> was closed first (see above — it was a test-data bug). Then both
> animation smoke scenarios were added to `scripts/smoke_test.py`:
>
> - `characterize_3D` — POSTs 3D data to `/CharacterizeData/3/` with
>   `animationSize=320x240`, extracts the
>   `/temp/ScatterAnimation<...>.gif` href from the result body, reads
>   the file off disk, asserts `PIL.Image.open(path).n_frames >= 2`.
> - `polynomial_quadratic_3D` — was modified in the same session to
>   enable animation; same pattern, asserts
>   `/temp/SurfaceAnimation<...>.gif` has ≥ 2 frames.
>
> On-disk reads (not HTTP) because Django under Waitress with
> `DEBUG=False` doesn't serve `STATIC_URL` paths — that's nginx's
> job in production. Smoke runs on the same machine, so
> `open("temp/<filename>")` is simpler and version-independent.
>
> The smoke suite is now at 10 scenarios; all pass. The
> `ScatterAnimation` and `SurfaceAnimation` Pillow paths are end-
> to-end verified.

Historical notes, preserved:

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

## Investigate lifting the 4-worker cap on spawn platforms

**Symptom / constraint.** `platform_compat.get_parallel_process_count`
hard-caps at 4 workers on spawn platforms (Windows, macOS). On
fork platforms (Linux) the cap is `cpu_count`. On an 8- or 16-core
Windows box doing a FunctionFinder run or a many-report 3D fit,
this leaves half to three-quarters of the CPU idle.

**Why we picked 4 originally.** During the cross-platform migration
(2026-04-17) we measured spawned Pool workers at ~750 MB resident
each because each worker re-imports numpy / scipy / matplotlib /
pyeq3 / OpenBLAS from scratch — spawn doesn't inherit the parent's
memory. Running a full-cpu-count pool on an 8-core Windows box with
modest RAM committed ~6 GB of virtual memory just for the workers,
overflowing the default Windows pagefile and producing opaque
`ImportError: DLL load failed while importing _flapack` failures.
The 4-worker cap was a conservative fix that kept the symptom from
recurring without requiring deeper investigation. See
`docs/superpowers/specs/2026-04-17-cross-platform-design.md` §12.2.

**Why it might be worth revisiting.** Several things have changed
since 2026-04-17 that the 4-cap hasn't been re-evaluated against:

- numpy 2.4.4, scipy 1.17.1, matplotlib 3.10.8, Python 3.14.4 —
  each upgrade likely shifted per-worker memory footprint
  (probably up, but worth measuring).
- Python 3.14 introduced subinterpreters as a supported feature
  (PEP 734). They share more memory than subprocesses. Not a drop-
  in replacement for `multiprocessing.Pool` but a potential
  alternative pattern.
- Lazy-import refactors inside `ParallelWorker_CreateReportOutput`
  and FunctionFinder's worker function could defer the heaviest
  imports until actually needed per-report, reducing the baseline.
- `Pool(initializer=...)` is already being used implicitly (workers
  are reused across tasks within a Pool), so the one-time import
  cost is amortized — the only question is how many concurrent
  workers the system can hold.
- Modern Windows machines commonly have 16-32 GB RAM; the pagefile
  concern is less sharp than on an 8 GB laptop.

**Where to pick up.**
1. **Measure baseline today.** Add an instrumentation pass that
   calls `psutil.Process(pid).memory_info().rss` inside
   `ParallelWorker_CreateReportOutput` right after the expensive
   imports are resolved. Run the `polynomial_quadratic_3D` smoke
   scenario with the animation enabled (already in smoke as of
   commit `debdafe`). Collect per-worker peak RSS and compare to
   the 750 MB estimate.
2. **Try lifting the cap on the measurement box.** Pass
   `cpu_cap=8` to `get_parallel_process_count` from the 3D scenario
   (or temporarily patch `platform_ceiling`). Re-run smoke. If it
   still succeeds and no pagefile pressure is observed, the 4-cap
   was overly conservative for this hardware class.
3. **If step 2 works, decide on a dynamic cap.** Options:
   (a) compute cap from `psutil.virtual_memory().total`
   (e.g., `max(4, total_gb // 2)`); (b) read from an env var
   `ZUNZUN_MAX_WORKERS` so the user can tune per-machine;
   (c) keep 4 as default but expose `cpu_cap` kwarg through the
   form so power users can override.
4. **If step 2 fails or introduces flakiness**, the 4-cap is
   load-bearing and should stay. Document the measurement.
5. **Stretch: investigate subinterpreters.** Python 3.14's
   `_interpreters` stdlib module (PEP 734) shares memory better
   than subprocesses. Would require a significant rewrite of the
   Pool dispatch logic — only worth it if the memory ceiling is
   actually the bottleneck.
6. **Reference: pyeq3's Multifit uses queue-based workers.**
   `pyeq3.Utilities.Multifit.FitModelsInParallel` (added upstream
   in equations-project's PR #7) ranks many equations using
   `multiprocessing.Queue` + explicit worker processes rather than
   `multiprocessing.Pool`. On Windows-spawn platforms, queue-based
   workers can be less fragile than Pool because each worker's
   lifecycle is independent — a worker that dies during import
   doesn't silently consume a Pool slot. Worth studying as a
   reference implementation when refactoring `FunctionFinder`'s
   `PerformWorkInParallel`, since zunzun and pyeq3 share the
   dependency stack (numpy, scipy, pyeq3, matplotlib) and the same
   per-worker import cost drives the 750 MB estimate.
   File to read: `pyeq3/Utilities/Multifit.py` around
   `FitModelsInParallel` + `parallelWorker` + `SubmitTasksToQueue`.

**Risk of lifting the cap without measurement.** The original
symptom (`ImportError: DLL load failed while importing _flapack`)
is noisy but not fatal — Django's try/except swallows it, logs to
`temp/{pid}.log`, and the fit appears to succeed with missing
reports. Easy to miss. Any cap-lifting change must be validated
against smoke on at least the target hardware class (16 GB
Windows 11 is a good baseline) before merging.

**Not in scope of any current branch.** This is a performance
optimization, not a correctness fix. It deserves its own branch
with its own spec and before/after benchmark measurements
captured in the design doc.
