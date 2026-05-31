# BACKLOG — known deferred issues and improvements

Tracked items that are real defects, loose ends, or quality improvements
worth doing eventually but scoped out of the current branch. Each entry
documents the symptom, the hypothesis, what we *didn't* do, and where to
pick up from. Closed items are preserved with strikethrough headings for
historical reference.

Renamed from `TODO.md` on 2026-04-28 — the file's scope had grown beyond
"things broken right now" to also cover quality refactors and cosmetic
modernization, which `BACKLOG` captures more honestly.

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
>
> **2026-05-28 addendum.** The `multiprocessing.Pool.apply_async().get()` hang described in the historical notes below — where a silent worker death would block the parent indefinitely — is now structurally fixed by the parallel-perf refactor (spec: `docs/superpowers/specs/2026-05-28-parallel-perf-design.md`). `CreateOutputReportsInParallelUsingProcessPool` was ported to `concurrent.futures.ProcessPoolExecutor`, which raises `BrokenProcessPool` on worker death instead of hanging. The `polynomial_quadratic_3D` scenario runs as part of the default smoke suite (`scripts/smoke_test.py`) and passes on the 22-core Windows acceptance run.

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

## ~~Complete ZunZunNG rebrand in user-facing strings~~ RESOLVED 2026-04-20

> **Resolution.** Landed on a dedicated `zunzunng-branding` feature
> branch and merged to master via `--no-ff` (merge commit `c013b87`,
> implementation commit `9d3ba63`). Applied the five substitution
> rules from the design spec across 19 files: display-text
> `ZunZunSite3` → `ZunZunNG`, lowercase `zunzunsite3` → `zunzunng`,
> bitbucket upstream URL → `github.com/kiloscheffer/zunzunng`, legacy
> Google-group URL → `https://groups.google.com/g/findcurves`,
> display label → `FindCurves Google Group`. `about.html` rewritten
> as two sections preserving James R. Phillips's original prose
> byte-for-byte. pytest 78/78 + smoke all-scenarios stayed green
> before and after.
>
> Intentional residue: 3 `ZunZunSite3` matches remain in
> `templates/zunzun/divs/about.html` — the NG section's "fork of
> ZunZunSite3" description, the "About the original ZunZunSite3"
> heading, and Phillips's verbatim nickname-origin sentence — all
> required by the spec's preserved-attribution design. Other
> Phillips repos in `generic_page_template.html` footer
> (`zunzunsite` without the 3, `FlaskFit`, `CherryPyFit`, `BottleFit`,
> etc.) remain on their original bitbucket URLs per spec Non-Goals.
>
> See `docs/superpowers/specs/2026-04-20-zunzunng-branding-design.md`
> and `docs/superpowers/plans/2026-04-20-zunzunng-branding.md` for
> design and execution records.
>
> Historical notes below, preserved for reference.

**Symptom / exposure.** As of 2026-04-20, the top-level project
identity was renamed from ZunZunSite3 to ZunZunNG in `pyproject.toml`,
`CLAUDE.md`, `README.txt`, and `CHANGELOG`, and the code was pushed to
`github.com/kiloscheffer/zunzunng`. However, ~25 user-visible display
strings and URLs still say "ZunZunSite3" or reference
`bitbucket.org/zunzuncode/zunzunsite3`:

- **HTML templates (10 files).** `templates/zunzun/home_page.html`
  (welcome header, Bitbucket link, Google-group alt text × 2),
  `templates/zunzun/divs/about.html` (heading + prose), and the page
  titles / header strings in `function_finder_interface.html`,
  `function_finder_results.html`, `generic_error.html`,
  `generic_page_template.html`, `invalid_form_data.html`,
  `list_all_equations.html`, `feedback_reply.html`, and
  `divs/feedback_entry.html`.
- **View-generated HTML (`zunzun/views.py`).** `header_text` for the
  home page and list-all-equations page (3 sites); feedback-email
  subject line (`ZunZunSite3 Feedback Form`); cookie-stale error
  message.
- **LRP-generated HTML / PDF (`zunzun/LongRunningProcess/*.py`).**
  `FittingBaseClass.py`, `FunctionFinder.py` × 2,
  `FunctionFinderResults.py` × 2,
  `StatusMonitoredLongRunningProcessPage.py` × 5 produce `title_string`
  and `header_text` strings. `StatusMonitoredLongRunningProcessPage.py`
  also hard-codes the PDF watermark URL
  (`https://bitbucket.org/zunzuncode/zunzunsite3`) and the
  `'ZunZunSite3'` credit line drawn on every generated PDF.
- **Graph watermark (`MatplotlibGraphs_2D.py`).** Every 2D plot has
  `ax.text(..., 'zunzunsite3', ...)` as a semi-transparent watermark.
- **Internal log strings (low priority).** `apps.py` emits
  `"zunzunsite3: missing external binaries on PATH"` at startup.
  `platform_compat.py`'s module docstring opens with
  `"""Platform-specific shim layer for zunzunsite3."""`.

**When we hit it.** 2026-04-20, the ZunZunNG rebrand commit
introducing the top-level rename. The scope was intentionally kept
narrow — the historical design specs, plans, and CHANGELOG entries
reference "zunzunsite3" as the project name at the time of the work,
and rewriting those would rewrite history. User-facing branding is
separable follow-up work.

**Hypothesis.** A straightforward search-and-replace over the
filtered file set (templates/ + zunzun/ only, excluding docs/ and
TODO.md and fork-pattern-reviewer agent), changing `ZunZunSite3` →
`ZunZunNG`, `zunzunsite3` → `zunzunng` (carefully, since "zunzunng"
is lowercase branding — the package name — while display headers
use mixed case "ZunZunNG"), and
`https://bitbucket.org/zunzuncode/zunzunsite3` →
`https://github.com/kiloscheffer/zunzunng`. The `about.html` prose
("The name of the project, ZunZunSite3, is taken from my wife's
Burmese nickname") is a personal attribution from Ray Harrington —
it should either be rewritten to add an NG-fork note or removed
entirely; silent substitution would be dishonest.

**Where to pick up.**
1. Enumerate: `grep -ri 'zunzunsite3\|ZunZunSite3' templates/ zunzun/`
   produces the canonical list (~25 sites).
2. Apply substitution per file, manually reviewing each hit for
   context (URL vs display header vs log string vs watermark).
3. Rewrite `templates/zunzun/divs/about.html` prose to preserve
   James R. Phillips's origin-story attribution ("dedicated to
   Jesus of Nazareth, and was written by James R. Phillips" +
   "The name of the project, ZunZunSite3, is taken from my wife's
   Burmese nickname") while framing the NG fork. Rationale: the
   original name has personal meaning to the original author;
   erasing the attribution would be disrespectful AND a BSD-2-clause
   violation, but so would silently rewriting it so the "my wife"
   phrasing implicitly attributes to the current maintainer. The
   clean solution is two adjacent sections — "About the original
   ZunZunSite3 (James R. Phillips, 2016)" preserving the original
   prose verbatim, and "About the NG fork (Kilo Scheffer, 2026-)"
   with the fork's own framing.
4. Update the smoke test's assertion strings if any match on
   `ZunZunSite3` header text — grep `scripts/smoke_test.py` for
   `"ZunZun"` after the template edits.
5. Verify with `uv run python scripts/smoke_test.py`
   — the 12 scenarios include home-page, characterize, function
   finder, and evaluate-at-a-point, all of which render the
   affected templates.

**Not in scope of the NG-rebrand branch.** The top-level rename
delivered: project identity, GitHub repo, version tag. User-facing
display strings are their own surface (site-visible), and merging
them in the same commit would make the rebrand unreviewable. A
dedicated `nailing-zunzunng-branding` branch with its own spec is
the right shape for this.

## ~~Investigate lifting the 4-worker cap on spawn platforms~~ RESOLVED 2026-05-28

> **Resolved 2026-05-28** by `docs/superpowers/specs/2026-05-28-parallel-perf-design.md` (spec) and `docs/superpowers/plans/2026-05-28-parallel-perf.md` (12-task implementation plan). The hardcoded `platform_ceiling = 4 if uses_spawn else cpu_count` is gone; the per-fit worker count is now resolved by `ZUNZUN_MAX_WORKERS` env > `settings.MAX_PARALLEL_WORKERS` > auto-detect `min(cpu_count, available_RAM / 200 MB)`. Empirical 22-core Windows acceptance run (2026-05-28) confirmed full-core utilization without OpenBLAS memory contention — the `FitPool` sets `OMP_NUM_THREADS / OPENBLAS_NUM_THREADS / MKL_NUM_THREADS=1` in spawn workers to prevent the BLAS thread-pool init bomb. Per-worker RSS measured at ~140 MB (vs. the 750 MB pessimistic estimate that motivated the cap). FunctionFinder 2D large scenario: 39.3 s wall time, 4,137 MB peak total RSS (12.9% of 31 GB). See spec §13 for the full acceptance numbers.

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

## ~~Factor out session.save() retry helper~~ RESOLVED 2026-05-29

> **Resolution.** New module `zunzun/session_helpers.py` exports
> `save_with_retry(session, ...)` and `load_with_retry(session, key, ...)`.
> All seven inline retry-loop sites collapsed:
>
> - 6 sites in `zunzun/views.py` (lines 252, 337, 427, 492, 513, 574)
> - 1 site in `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py`
>   (`SaveDictionaryOfItemsToSessionStore`)
>
> Each ~10-line `save_complete = False / saveRetries = 0 / while ...`
> block replaced by a single `save_with_retry(s)` call.
> `LoadItemFromSessionStore` also rewired to use `load_with_retry`,
> picking up the same retry semantics for SQLite-contention reads —
> see the companion BACKLOG entry "Robustness improvements in LRP
> child logging and session reads" resolution notes below for the
> read-side rationale.
>
> Pytest 133/133 green. Bundled with the BACKLOG #6 child-logging
> cleanup so the fork-pattern-reviewer agent's check could be updated
> once instead of twice.
>
> Historical notes below, preserved for reference.

**Symptom / exposure.** Every `session.save()` call inside the LRP child
process is wrapped in a 100-retry @ 10Hz loop because spawn-children
contend on the SQLite session DB. The canonical pattern is in
`StatusMonitoredLongRunningProcessPage.SaveDictionaryOfItemsToSessionStore`,
copy-pasted to other save sites. Easy to forget when adding a new save
site, and the only enforcement is the `fork-pattern-reviewer` agent's
grep for the literal retry loop.

**Why it's worth fixing.** DRY violation that creates an ongoing footgun.
Centralizing the retry into a single helper:

- Single source of truth for retry semantics (count, delay, exception
  scope).
- New save sites are obviously correct — `save_with_retry(s)` is hard
  to typo.
- The reviewer agent's check simplifies to "every session save is a
  `save_with_retry` call" instead of "every session save is followed
  by a 100-retry loop matching this exact shape."

**Where to pick up.**

1. Add `save_with_retry(session, *, max_retries=100, delay=0.1)` to
   `StatusMonitoredLongRunningProcessPage.py` (or a new
   `zunzun/session_helpers.py` if the helper count grows).
2. Replace each in-line retry loop with a single call. Find them with
   `grep -n 'session.save\|s.save\|.save()' zunzun/`.
3. Update `.claude/agents/fork-pattern-reviewer.md` to look for
   `save_with_retry` instead of the raw retry pattern.
4. Add a unit test covering the retry-on-failure path (mock a session
   that raises N times then succeeds).

**Not in scope of any current branch.** Pure refactor; no behavior
change. Worth a small focused commit when convenient.

## ~~Auto-coerce numpy values via custom JSONEncoder~~ RESOLVED 2026-05-29

> **Resolution.** Added `NumpyJSONEncoder` and `NumpySessionSerializer`
> to `zunzun/session_helpers.py`, and set
> `SESSION_SERIALIZER = "zunzun.session_helpers.NumpySessionSerializer"`
> in `settings.py`. numpy coercion now happens automatically at
> `session.save()` time, so the 10 `_json_native(...)` wrapper calls
> across the LRP subclass tree were removed and the `_json_native`
> helper itself deleted from `StatusMonitoredLongRunningProcessPage`.
>
> **Encoder is leaner than `_json_native` was.** `_json_native`
> recursively walked dicts / lists / tuples. The encoder only needs
> the two leaf cases `json` can't handle natively — `numpy.ndarray`
> (`.tolist()`) and `numpy.generic` (`.item()`) — because `json.dumps`
> already recurses into containers and only calls `default()` on
> unencodable leaves. Note `numpy.float64` is a subclass of `float`
> and serializes natively (never reaches `default()`), which is why
> the old explicit `.item()` cast on it was never load-bearing.
>
> **Sites changed:** 8 Fit* subclasses (`FitOneEquation`, `FitSpline`,
> `FitUserCustomizablePolynomial`, `FitUserDefinedFunction`,
> `FitUserSelectablePolyfunctional`, `FitUserSelectablePolynomial`,
> `FitUserSelectableRational`) + `FunctionFinder` (×2 calls). Each
> `_json_native({...})` wrapper became a bare dict literal; the
> `from .StatusMonitoredLongRunningProcessPage import _json_native`
> imports were dropped (FunctionFinder kept `_ReportsPipelineAborted`).
> Stale comment in `views.py` updated.
>
> **Tests:** added `test_numpy_serializer_roundtrips_numpy_values`
> (direct serializer dumps/loads over scalar + 1D/2D array + nested
> dict + tck-style tuple) and
> `test_lrp_save_load_roundtrips_numpy_via_serializer` (end-to-end
> save → SQLite → fresh-SessionStore reload, proving the global
> `SESSION_SERIALIZER` wiring fires). Pytest 135/135.
>
> **Why the global wiring is safe:** numpy coercion is a strict
> superset of default behavior — it only activates for numpy leaves,
> which never appear in non-LRP sessions (main request session stores
> session keys + cookie flags). `NumpySessionSerializer.dumps` matches
> Django's stock `JSONSerializer.dumps` byte-for-byte except the
> `cls=` encoder, so existing session blobs stay compatible.
>
> Historical notes below, preserved for reference.

**Symptom / exposure.** Django's default `JSONSerializer` (the session
backend's serializer since the JSON-native session migration) doesn't
know how to serialize numpy types — neither `numpy.float64` scalars nor
`numpy.ndarray` arrays. The codebase works around this with
`_json_native(...)` calls at every `SaveSpecificDataToSessionStore`
site in the LRP subclass tree, manually casting values before the
write so JSON serialization succeeds.

**Why it's worth fixing.** Same shape as the retry-loop issue: a
copy-pasted workaround that's easy to forget on new save sites.
The `_json_native` helper itself is fine; the problem is having to
remember to call it. A custom `JSONEncoder` that handles numpy
coercion automatically removes the requirement to remember.

**Where to pick up.**

1. Define a `JSONEncoder` subclass (alongside `_json_native`, or
   replacing it) that overrides `default()` to coerce numpy scalars
   and arrays to plain Python primitives. The existing
   `_json_native` logic is the body — just lifted into the encoder.
2. Either subclass Django's `JSONSerializer` to inject the encoder,
   or set `SESSION_SERIALIZER` to a custom serializer in
   `settings.py`.
3. Remove `_json_native` calls from save sites once the encoder
   handles coercion at serialization time.
4. Add a unit test that round-trips a session containing numpy
   values (scalar + 1D array + nested dict) through the new
   serializer.

**Not in scope of any current branch.** Pure refactor; no behavior
change. Cross-cutting touch (every save site changes), so worth
doing in one focused commit rather than incrementally.

## ~~Replace pid_trace.py with proper logging~~ RESOLVED 2026-05-29

> **Resolution.** `zunzun/LongRunningProcess/pid_trace.py` deleted.
> Per-LRP trace logging now routes through `_logger =
> logging.getLogger(__name__)` defined at module level in the four
> files that previously had text-bearing `pid_trace.pid_trace("...")`
> calls (`DataObject.py`, `FitOneEquation.py`,
> `StatisticalDistributions.py`, `StatusMonitoredLongRunningProcessPage.py`).
> A `LOGGING` config block in `settings.py` makes
> `zunzun.LongRunningProcess` reach the desired level via the
> `ZUNZUN_LRP_LOG_LEVEL` env var (defaults to `WARNING`). Pytest
> 133/133 green.
>
> **Departure from BACKLOG recipe — explicit.** The entry said
> "replace each `pid_trace.<function>(...)` call with
> `logging.getLogger("zunzun.lrp").debug(...)`." Auditing the 89
> callsites showed:
>
> - 55 bare `pid_trace.pid_trace()` calls with no message — empty
>   positional markers from a printf-debugging era. Translating
>   these to `_logger.debug("")` would just move cognitive load
>   from "what's `pid_trace`?" to "why all these empty debug calls?"
>   Deleted them. A future contributor who wants per-step tracing
>   can re-add `_logger.debug("...")` at the same spots with a
>   message that actually says something.
> - 11 `pid_trace.pid_trace("text")` calls with real debug content.
>   Converted to `_logger.debug("text")`.
> - 23 `pid_trace.delete_pid_trace_file()` calls — these used to
>   delete the per-process trace file at the end of a code block.
>   No analog in `logging` (file handlers don't get torn down per
>   call), so deleted entirely.
>
> Net: 89 callsites → 11 meaningful `_logger.debug(...)` calls.
> The "remove cognitive load" intent of the entry is better served
> than the literal recipe would have been. Logger name uses
> `__name__` per module (matching `child_payload.py`'s convention)
> rather than a single shared `"zunzun.lrp"` — both work for the
> env-var control knob since `zunzun.LongRunningProcess` is the
> common prefix.
>
> Updated `docs/internals/active-gotchas.md` and `AGENTS.md`
> (gitignored) to point at the new logger pattern.
>
> **Codex review on PR #16 caught a real defect in the first cut.**
> The original `LOGGING` config attached no handler and the child's
> `logging.basicConfig(... temp/{pid}.log ...)` only fires inside
> exception handlers — by which point successful trace points have
> already run. Result: `ZUNZUN_LRP_LOG_LEVEL=DEBUG` produced no output
> for normal-flow tracing. Fixed in commit by adding
> `_setup_child_root_logging()` to `child_payload.py` and calling it
> at the top of `_run_fit_child` (after `django.setup()`, before any
> `_logger.debug(...)` in `PerformAllWork` fires). The
> `settings.LOGGING` docstring is also corrected to explain that
> parent-side trace messages are NOT routed by default and require
> the user to add a handler.
>
> Historical notes below, preserved for reference.

**Symptom / exposure.** `zunzun/LongRunningProcess/pid_trace.py`
contains two functions that `return` at the top — explicit no-ops
in production. Calls to them are scattered through
`StatusMonitoredLongRunningProcessPage.py` as debugging hooks. To
enable per-process trace files, the maintainer is expected to
remove the early `return`s in source. CLAUDE.md documents this as
"dormant by design."

**Why it's worth fixing.** Source-edit-to-enable-debug is a smell
that predates Python's modern logging conventions. With proper
logging:

- A future maintainer enables per-process traces by setting a
  logger level via env var or a `LOGGING` dict in `settings.py` —
  no source edits, no commit churn.
- Output integrates with Django's logging configuration, so it
  goes wherever other Django logs go (file, stderr, journald).
- Free metadata: timestamps, process IDs, log levels.
- The `pid_trace.py` file itself can be deleted, removing one
  small but persistent piece of "what's this for?" cognitive
  load on new contributors.

**Where to pick up.**

1. Replace each `pid_trace.<function>(...)` call with
   `logging.getLogger("zunzun.lrp").debug(...)` (or a similar
   per-LRP logger name).
2. Add a `LOGGING` config block to `settings.py` with the
   per-LRP logger declared at WARNING by default; document how
   to bump to DEBUG for trace mode.
3. Delete `zunzun/LongRunningProcess/pid_trace.py` and any
   `from . import pid_trace` lines.
4. Update `CLAUDE.md`'s "`pid_trace.py` is dormant by design"
   subsection — replace it with a "Per-LRP logger" subsection
   pointing at the `LOGGING` config.

**Not in scope of any current branch.** Cleanup; no production
behavior change in the dormant state.

## ~~Convert CommonToAllViews to Django middleware~~ RESOLVED 2026-05-29

> **Resolution.** Created `zunzun/middleware.py` with
> `CommonToAllViewsMiddleware` and registered it in
> `settings.MIDDLEWARE` after `SessionMiddleware`. The middleware now
> handles zombie reap, IP block check, HTTP method gate (raising
> `Http404` for non-GET/POST), and rate-limit sleep. Removed all five
> `if CommonToAllViews(request): raise django.http.Http404` blocks
> from `zunzun/views.py` and deleted the `CommonToAllViews` function
> entirely. Pytest 133/133 green, including the rate-limit test
> (`tests/test_ratelimit.py`).
>
> **Design wrinkles found in execution that the original entry
> didn't anticipate:**
>
> - The entry's bullet list claimed `CommonToAllViews` did a
>   load-average check; it didn't. That was wishful documentation.
>   The actual responsibilities were: zombie reap, IP block, method
>   gate, rate-limit sleep.
> - Every `if CommonToAllViews(request): raise Http404` block was
>   dead code: `CommonToAllViews` never returned `True` — only
>   `False` or raise. The `if` evaluated to `False` always; the
>   `raise Http404` was never reached. Middleware conversion turned
>   those checks into actual `Http404` paths (now in the middleware
>   itself).
> - The entry suggested registering after `RatelimitMiddleware`, but
>   django-ratelimit is used as a `@ratelimit(...)` **decorator**,
>   not as middleware. The first cut put the rate-limit sleep in the
>   middleware's `process_response` — Codex's review on PR #15
>   correctly flagged that this loses slammer back-pressure on
>   ``LongRunningProcessView``: the fit child spawn would happen
>   *before* the 5 s sleep. Fixed by moving the sleep into a small
>   ``rate_limit_sleep`` decorator stacked below ``@ratelimit`` on
>   each rate-limited view, so the sleep runs after `request.limited`
>   is set but before the view body executes. Documented in the
>   middleware module docstring and in `AGENTS.md` §
>   Rate limiting + `docs/internals/active-gotchas.md`.
>
> Also updated `.claude/agents/fork-pattern-reviewer.md` check #6
> from "every entry-point view must call `CommonToAllViews`" to
> "verify `CommonToAllViewsMiddleware` remains in
> `settings.MIDDLEWARE`."
>
> Historical notes below, preserved for reference.

**Symptom / exposure.** Every view function in `zunzun/views.py`
manually calls `CommonToAllViews(request)` at the top. The
function performs three pieces of housekeeping:

- Zombie-child reap (`platform_compat.reap_completed_children()`).
- Rate-limit sleep (5 seconds if `request.limited` is set by
  django-ratelimit).
- Load-average check / log via `platform_compat.get_loadavg()`.

If a new view forgets to call `CommonToAllViews`, none of this runs
for that route. The only enforcement is "remember" plus the
`fork-pattern-reviewer` agent grepping for `CommonToAllViews(`
near the top of every view.

**Why it's worth fixing.** Django middleware is the canonical
mechanism for "do something on every request." Converting:

- Auto-applies to every view, including future ones.
- Removes the manual-call requirement entirely.
- Removes one of the `fork-pattern-reviewer` agent's checks
  (the middleware presence becomes the gate).
- Better Django idiom — easier for new contributors to navigate.

**Where to pick up.**

1. Create `zunzun/middleware.py` with a class:

   ```python
   class CommonToAllViewsMiddleware:
       def __init__(self, get_response):
           self.get_response = get_response
       def __call__(self, request):
           # zombie reap
           # rate-limit sleep
           # load-average check
           return self.get_response(request)
   ```

2. Add the class to `MIDDLEWARE` in `settings.py`, after
   `RatelimitMiddleware` so `request.limited` is already set
   when the middleware runs.
3. Remove the manual `CommonToAllViews(request)` call from every
   view in `zunzun/views.py`.
4. Either delete the `CommonToAllViews` function once nothing
   calls it, or keep it as the middleware's implementation
   detail.
5. Update `.claude/agents/fork-pattern-reviewer.md` — replace the
   "every entry-point view must call `CommonToAllViews`" check
   with "the middleware class is registered in `settings.MIDDLEWARE`."

**Not in scope of any current branch.** Pure refactor; no behavior
change visible to users.

## Modernize HTML/CSS in templates (substantially complete)

**Status:** ten passes landed between 2026-04-28 and 2026-04-30. The
site now renders in HTML5 with semantic landmarks (`<header>` /
`<main>` / `<footer>` / `<nav>` / `<h2>` / `<h3>`), no deprecated
elements, no inline presentation attributes, no inline display styles,
and a class-based show/hide system. Remaining work is ergonomic /
accessibility polish — none of it blocks correctness or modern-browser
compatibility.

**Pass 1 (done — commit `0011366`):**

- Added `modern-normalize` and `simple.css` via `<link>` tags in
  `generic_page_template.html`.
- Removed obsolete elements: `<center>`, `<font>`, `<basefont>`,
  `<style type="text/css">` → `<style>`.
- Removed `border="0"` on images.
- Replaced `<HR WIDTH="X%">` with `<hr style="width:X%">`.
- 27 templates touched, -8 net lines.

**Pass 2 (done — commit `fe8f6af`):**

- Upgraded HTML 4.01 DOCTYPE → `<!DOCTYPE html>` in the 3 templates
  that declared one.
- Wrapped `generic_page_template.html`'s page-level structure in
  semantic `<header>` / `<main>` / `<footer>` so simple.css's
  body-scoped styles apply correctly (footer auto-centers, content
  gets main padding).
- Removed non-conforming attributes: `cellpadding`, `cellspacing`,
  `valign`, `nowrap` (35 sites across templates).

**Pass 3 (done — commit `b5666a2`):**

- Lowercased all HTML tag names (`<TABLE>` → `<table>`, etc.) across
  38 templates and 4 JavaScript files that contain HTML string
  literals. ~1500 substitutions, perfect zero-net diff (pure case
  change). Helper script preserved at
  `scripts/_lowercase_html_tags.py`.

**Pass 4 (done — commit `fc26ec0`):**

- Lowercased all HTML attribute names (`ALIGN=` → `align=`, etc.)
  across 35 templates. Boolean attribute `SELECTED` (11 instances)
  also lowercased. Attribute *values* deliberately preserved
  (`align="CENTER"` becomes `align="CENTER"` — name lowercased,
  value as-is). ~339 substitutions.

**Pass 5 (done — commit `ae7e94a`):**

- Lowercased presentation-keyword *values* via whitelist (CENTER,
  LEFT, RIGHT, JUSTIFY, TOP, BOTTOM, MIDDLE; SUBMIT, BUTTON, RESET;
  POST, GET). ~119 substitutions across 26 templates. Identifier
  values like `id='FUNCTION'` (read by the matrix-selector JS via
  `d.layers['FUNCTION']` / `d.all['FUNCTION']`) and `id="introDiv"`
  deliberately preserved in their original case.

**Pass 6 (done — commit `527ec7b`):**

- Added a CSS reset to neutralize simple.css's data-table styling
  globally for layout tables: `border-collapse: collapse`,
  `border: none` on table + cells, reduced cell padding (0.15rem
  vertical / 0.25rem horizontal), suppressed
  `tbody tr:nth-child(odd|even)` background alternation. Initially
  added to an inline `<style>` block in `generic_page_template.html`;
  later relocated to `static/custom.css` during the extract-custom-css
  pass (commit `602e84b`).

**Pass 7 (REVERTED — commit `fa874d4`):**

- Attempted CSS fixes for two regressions surfaced by pass 6's
  table reset (margin: 0 wiped browser default `<table align=center>`
  centering; simple.css `<header>` banner styling appeared after
  pass 2 wrapped header content in `<header>`). The fix landed but
  introduced its own visual issue and was reverted via `fa874d4`.
  The header-bar concern was subsequently fixed by the
  `header-subtitle-split` branch (commit `878dfb2`, merged
  `caa4f38`) which split brand `<h1>` from page-specific subtitle
  `<p>`, plus the `9bdf5c5` "Template cleanup, scripture removal,
  and header/footer polish" pass.

**Pass 8 (done — commit `e34c8f6`):**

- Bulk attribute cleanup. Removed all `align=` (221 sites across
  36 files), `border=` (35 sites, 18 files), `size=1` on `<select>`
  (8 sites), `style="font-size:larger"` on `<span>` (14 sites),
  `style="text-align:..."` (4 sites), `align="Absmiddle"` on `<img>`
  (1 site), dead `onAbort="Load();"` (1 site).
- Security: added `rel="noopener noreferrer"` to all 8
  `<a target="_blank">` anchors. Quoted 2 unquoted `href=` URLs.
- Added layout utility classes (`text-center`, `text-left`,
  `text-right`, `gap-sm`, `gap-md`, `gap-lg`, `bordered`,
  `hr-half`, `hr-three-quarter`) to `static/custom.css`.
- 38 files changed; +409 / -350 net.

**Pass 9 (done — commit `9eb16eb`):**

- Semantic restructuring. Converted 14 `<b><span>` pseudo-headings
  and 20 standalone `<b>X</b><br><br>` patterns to `<h2>` (sed-
  driven). 8 sub-section labels demoted to `<h3>` (case-by-case:
  Matrix of Functions × 3, Graph Size + Animation Size in
  graph_size_div, Example UDFs / Help / Constants in
  user_defined_function_entry_div). 2 wrapper-div `<b>`s converted
  to `<h2>`. 4 `<input type="button">` → `<button type="button">`.
- 3 top-of-page navigation tables (`home_page.html`,
  `function_finder_interface.html`,
  `characterize_data_or_statistical_distributions_interface.html`)
  converted to `<nav class="dropdown-nav">` with `<label for="sN">`
  for each select, replacing the pseudo-`<th>` column-header
  pattern with proper form labels.
- Added `.dropdown-nav` flexbox CSS rules.
- 4 inline `<b>` retained as intentional inline emphasis (Hint,
  NOTE, Advice, equation displayName).
- Final state: 49 `<h2>` + 8 `<h3>` semantic headings (was 0).
- 37 files changed; +164 / -173 net.

**Pass 10 (done — commit `42cdff2`, plus follow-up fix `94ac48c`):**

- Show/hide system migrated from `name="hideable_div"` + inline
  `style="display:none"` (with jQuery `.css('display', ...)`) to
  `class="hideable hidden"` (with jQuery `.addClass`/`.removeClass`).
- 47 hideable divs across 28 files migrated. 5 jQuery edit sites
  in `generic_page_template.html` (`$(document).ready` + `f1`/`f2`/
  `f3`/`f4`).
- Added `.hidden { display: none }` to `static/custom.css`.
  `.hideable` is a marker class with no styles; it's the selector
  jQuery uses to find the show/hide elements.
- One transformational commit (not the originally-planned two-step
  additive-then-cleanup) because CSS specificity blocks the
  additive approach: inline `style="display:none"` (specificity
  1000) beats `.hidden { display: none }` (specificity 10), so
  removing the class via JS wouldn't actually show the div if the
  inline style remained. Single-pass transformation collapsed both
  steps.
- Follow-up fix `94ac48c`: `templates/zunzun/divs/historical_note.html`
  had a leftover `style="display:block;"` (pre-existing oddity) that
  the old jQuery `.css('display', 'none')` system masked but the
  class-based one couldn't override. Cleaned up to
  `class="hideable hidden"` matching the rest of the divs.
- 34 files changed; +64 / -55 net.

---

**Remaining work (deferred from passes 8-10):**

The following patterns remain in the templates as of commit `d61b2c7`,
with reasons each was deferred from passes 8-10. None of them block
correctness or modern-browser compatibility — they're ergonomic /
accessibility polish.

1. **`<br><br>+` runs (~41 sites across ~20 files):** mid-paragraph
   visual spacing. Most pre-pass-9 BR runs were after `<b>X</b>`
   pseudo-headings and got cleaned up incidentally when those became
   `<h2>` (which has natural margin-bottom). The remainder are
   between paragraphs of prose (about page, historical note,
   function finder advice, UDF help, etc.). Cleaning each requires
   deciding: wrap surrounding text in `<p>` so paragraphs get
   margin-bottom automatically, or replace the BR run with a CSS
   spacing utility on a wrapper. `grep -rE '<br><br>'
   templates/ --include='*.html'` lists them.

2. **`<hr style="width:N%">` (6 sites):** decorative tapered
   horizontal rules for visual section breaks in
   `list_all_equations.html` and `home_page.html`. Parametric inline
   CSS rather than a deprecated pattern. Could be moved to specific
   CSS classes (`.hr-30`, `.hr-45`, `.hr-60` to complement the
   existing `.hr-half` and `.hr-three-quarter`) or kept as-is.
   Cosmetic preference, no correctness issue.

3. **Inline `style="background-color:{{ color }}"` on coefficient-
   picker `<td>`s (19 sites in `polyfunctional_selection_div.html`,
   `polynomial_customization_div.html`,
   `polyrational_selection_div.html`):** **JS-coupled.** The
   matrix-selector JS files in `templates/zunzun/javascript/` read
   `td.style.backgroundColor` to determine selected state; moving
   to CSS classes requires a paired JS rewrite. Deferred with the
   JS modernization (see "Modernize legacy DOM access in
   matrix-selector JavaScript" entry below).

4. **Layout tables in `divs/*.html` form-field partials (~25
   templates):** most are paired
   `<tr><td>label</td><td>{{ form.field }}</td></tr>` patterns that
   could become `<dl>` (definition lists) or flexbox rows. Audit
   each — some are genuinely tabular (coefficient lists, equation
   listings) and should stay tables but get `<thead>`/`<tbody>` for
   accessibility. Pass 9 only converted the obvious nav tables; the
   form-field tables are case-by-case work.

5. **`equation_fit_or_characterizer_results.html` top nav table:**
   4-column variable-width nav with conditional
   `{% if equationInstance %}` and `{% if dimensionality != '1' %}`
   column rendering. Restructuring to `<nav class="dropdown-nav">`
   is feasible but the conditional-column logic makes it
   substantially more involved than the 3 nav tables converted in
   pass 9. Deferred for a focused follow-up.

6. **`function_finder_results.html` data table:** genuinely tabular
   data (rows of equation results: Model Plots / Contour Plots /
   Error Plots / Statistics). Should *stay* a `<table>`. Current
   markup doesn't have `<thead>` / `<tbody>` separation; adding
   them would improve accessibility (screen readers announce header
   rows correctly) and let CSS target the header row distinctly.

7. **`<label>` on every form `<input>`:** for accessibility (screen-
   reader compatibility, click-on-label-focuses-input). Most form
   inputs in `divs/*.html` are rendered via Django's
   `{{ form.field }}` without a paired `label_tag`. Fix requires
   changing each rendering site to
   `{{ form.field.label_tag }}{{ form.field }}` and deciding how
   labels integrate with the existing layout-table structure (which
   itself is partly pending — see #4 above). Worth doing alongside
   the layout-table work in #4.

**Not in scope of any current branch.** All deferred items are
ergonomic improvements rather than bug fixes; pick them up
individually as small focused commits when convenient.

## ~~Modernize legacy DOM access in matrix-selector JavaScript~~ RESOLVED 2026-05-31

> **Resolution.** Landed on `feat/matrix-selector-js-modernization`. Spec:
> `docs/superpowers/specs/2026-05-31-matrix-selector-js-modernization-design.md`
> (local / gitignored per repo convention). The selection state moved off the
> inline `style="background-color:rgb(...)"` attribute and onto a `selected`
> CSS class; the legacy Netscape/IE branches and both `eval()` calls are gone.
>
> **As-built (deviates from the recipe below — corrections noted):**
> - **The recipe's white/lightgray semantics were inverted.** It said white
>   `rgb(255,255,255)` = unselected and lightgray `rgb(211,211,211)` =
>   selected. The live code (all 4 JS files + the 3 Python builders) is the
>   opposite: **white = SELECTED** (hidden input `'True'`, inset border,
>   included in the equation), **lightgray = unselected** (`'False'`, outset).
>   Following the recipe's `classList.add('selected')` mapping literally would
>   have silently flipped every coefficient selection. The bool->class mapping
>   is now pinned by `tests/test_matrix_selector.py`.
> - **The cells are built in-repo, not by pyeq3.** The clickable `<td>`s come
>   from the Django templates' `*ColorList` context vars, populated by
>   `FitUserSelectablePolyfunctional.py`, `FitUserCustomizablePolynomial.py`,
>   and `FitUserSelectableRational.py`. Each `*ColorList` tuple's first element
>   changed from an rgb string to a `selected` bool; `colorOffset` (string) ->
>   `offsetSelected` (bool). No pyeq3-ng release was needed.
> - **State is a class toggle, not add/remove against a no-default.** Default
>   `td.pick` now carries the lightgray + outset look (the inline style used to
>   supply the background); `td.pick.selected` is white + inset. The
>   single-source read/write helpers `isSelected()` / `setSelected()` live in
>   `JavascriptCommonToFunctionMatrices.js`, trimmed to just `c`, `maxCoeffs`,
>   `warning` plus those helpers (the `ns4`/`ie4`/`d`/`w`/`lg`/`ins`/`os`
>   globals are gone).
> - **CSS consolidated; legacy partial deleted.** The `td.pick` rule moved
>   into `static/custom.css` (new MATRIX PICKER CELLS section) and the
>   Netscape-era `templates/zunzun/polyfunctional_css_style.html`
>   `<style><!-- ... --></style>` partial + its `css_definitions` include were
>   removed.
>
> **This unblocks** HTML-modernization remaining item #3 (inline
> `style="background-color"` on coefficient-picker `<td>`s) — now done. Step 7
> below (lowercasing `id='FUNCTION'` now that the JS no longer keys on it) is
> left as optional future polish.
>
> **Verification:** `tests/test_matrix_selector.py` (7 tests) green; full
> `pytest` green; `ruff format` clean. Smoke does not exercise the click UI
> (it POSTs the hidden fields directly), so a manual click-through across 2D +
> 3D polyfunctional / polynomial-customization / polyrational pickers is the
> coverage for the interaction itself.
>
> Historical notes below, preserved for reference (including the inverted
> white/lightgray semantics in the original recipe — see the correction above).

**Symptom / exposure.** Four JS files in
`templates/zunzun/javascript/`:

- `JavascriptForFunctionMatrix2D.js` (147 lines)
- `JavascriptForFunctionMatrix3D.js` (165 lines)
- `JavascriptForRationalMatrix2D.js` (267 lines)
- `JavascriptForRationalMatrix3D.js` (165 lines)

drive the polyfunctional and rational matrix coefficient pickers
(the clickable `<td id="CPX{N}">` cells in
`polyfunctional_selection_div.html`,
`polynomial_customization_div.html`,
`polyrational_selection_div.html`). They use legacy DOM access
patterns from the Netscape 4 / IE 4 era:

- `document.layers[i]` — Netscape 4 only; that browser was last
  released 2002 and has been functionally extinct since ~2007.
- `document.all[i]` — IE 4-5 only; IE 5+ also supports
  `getElementById`, IE 6+ ships standard DOM, IE itself was retired
  by Microsoft in 2022.
- `eval("document.forms[0].elements." + dynamicName + ".value = ...")`
  for runtime form-field access by computed name. Modern equivalent:
  `document.forms[0].elements[dynamicName]`.

The functions branch on browser detection
(`if (ns4) { ... } if (ie4) { ... }`) and pick the right path; on
modern browsers both branches return false and the fallthrough path
runs. Roughly half the code in each file is dead-browser branches.

In addition, 19 inline `style="background-color:{{ color }}"`
attributes on the matrix-cell `<td>`s — the JS reads
`.style.backgroundColor` to determine selected state, comparing
against literal strings like `'rgb(255,255,255)'` (white = unselected)
and `'rgb(211,211,211)'` (lightgray = selected).

**Why it's worth fixing.**

- Drops ~50% of the code in those 4 JS files (the NS4/IE4 branches
  are dead code).
- Eliminates `eval()` (security smell, performance smell — Content
  Security Policy hostility).
- Decouples `<td>` styling from JS state. Moving inline
  background-color to CSS classes lets the existing simple.css /
  custom.css stylesheet drive appearance.
- Unblocks remaining-work item #3 in the HTML modernization section
  above ("Inline style="background-color" on coefficient-picker
  `<td>`s").

**Where to pick up.**

1. Replace `document.layers[id]` and `document.all[id]` with
   `document.getElementById(id)`. Delete the `if (ns4)` and
   `if (ie4)` branches.
2. Replace
   `eval("document.forms[0].elements." + name + ".value = ...")`
   with `document.forms[0].elements[name].value = ...` (no eval).
3. Replace `td.style.backgroundColor.replace(/\s/g, '') == 'rgb(...)'`
   "is selected" reads with `td.classList.contains('selected')`.
4. Replace `td.style.backgroundColor = 'rgb(211,211,211)'` writes
   with `td.classList.add('selected')`; replace
   `td.style.backgroundColor = 'rgb(255,255,255)'` with
   `td.classList.remove('selected')`.
5. Add a `.coefficient-picker .selected { background-color: #d3d3d3 }`
   (or similar) rule to `static/custom.css`. The unselected default
   is the surrounding cell background — no class needed.
6. Update `polyfunctional_selection_div.html`,
   `polynomial_customization_div.html`,
   `polyrational_selection_div.html` to remove the inline
   `style="background-color:..."` from the `<td>`s. Default state
   is "not selected"; JS adds `.selected` class when clicked.
7. Update `pass 5`'s preserved `id='FUNCTION'` exclusion note (in
   the modernization section above) — once the JS no longer reads
   `d.layers['FUNCTION']` / `d.all['FUNCTION']`, the case-preservation
   constraint goes away and `id='FUNCTION'` could be lowercased to
   match site convention. Optional.

**Verification.**

- pytest unaffected (no Python coupling).
- Smoke unaffected (smoke doesn't exercise the matrix-picker UI;
  it POSTs the polyfunctional/polynomial/polyrational forms with
  pre-set hidden field values, bypassing the click interaction).
- Manual test required: load
  `/Equation/2/Polynomial/User Customizable Polynomial/`
  (or any polyfunctional / rational equation), click coefficient
  cells, verify visual selection toggle. Submit; verify the hidden
  form fields (`polyFunctional_X*`, `polyRational_X_N*`,
  `polyRational_X_D*`, `polyRational_OFFSET`) carry the selected
  pattern through to the fit.

**Not in scope of any current branch.** Cleanup; no production
behavior change. Worth a small focused commit; ~50% line reduction
across 4 JS files plus the paired `<td>` template cleanup.

## Matrix-selector follow-ups (duplication + submit-sync) — deferred from JS modernization

**Surfaced by** the `/code-review xhigh` pass on
`feat/matrix-selector-js-modernization` (2026-05-31). None are regressions
from that PR — they are pre-existing structure the modernization left in place.
Bundled here because they all live in the same matrix-selector surface and are
best tackled together (and all need a manual click-through to verify, since
there is no automated coverage of the picker's click/submit path — smoke POSTs
the hidden fields directly).

**1. Cross-file JS duplication.** After the rewrite, the four matrix scripts in
`templates/zunzun/javascript/` are largely duplicated:
- `JavascriptForRationalMatrix3D.js` is byte-identical to
  `JavascriptForFunctionMatrix3D.js` except the `cT()` signature line
  (`cT(id)` vs `cT(id, unusedFor3D)`) — 60 of 61 lines.
- `readPolyFlags()` is byte-identical across `JavascriptForFunctionMatrix2D.js`,
  `JavascriptForFunctionMatrix3D.js`, and `JavascriptForRationalMatrix3D.js`
  (only the rational-2D variant genuinely differs, splitting `CPX_N`/`CPX_D`/
  `CPX_O`).
- The count→cap→toggle prologue of `cT()` (the `pickCells()` count loop, the
  `count >= maxCoeffs` alert gate, and `setSelected(target, !isSelected(target))`)
  is byte-identical in all four files (~18 lines × 4).

The shared `JavascriptCommonToFunctionMatrices.js` already hosts the selection
primitives (`pickCells`/`isSelected`/`setSelected`), so it is the natural home
for a shared `readPolyFlags` (polyfunctional form) + a `toggleWithLimit(id)`
helper, leaving only the rational-2D `readPolyFlags` and each file's
format-specific equation-preview builder local. **Risk:** the common file is
included by every matrix type, so a `readPolyFlags` defined there must be
overridden (not shadowed by accident) by the rational-2D file — include order
is common-first, so a later redefinition wins, but this is exactly the subtle
JS that breaks silently. Re-run the manual click-through for all three pickers
in 2D and 3D after any consolidation.

**2. Dead `unusedFor3D` param.** `JavascriptForFunctionMatrix3D.js`'s
`cT(id, unusedFor3D)` never reads the 2nd arg, yet the 3D templates pass
`cT(this.id,1)` (polyfunctional) / `cT(this.id,0)` (polynomial). Drop the param
and the `,1`/`,0` literals in the 3D divs, or document why 3D keeps an arg.

**3. Python 3D ColorList builder duplication.** The 3D `Polyfun3DColorList`
block (the 4-way `i==0&&j==0 / i>0&&j==0 / i==0&&j>0 / else` ladder) is
byte-identical between `FitUserSelectablePolyfunctional.py` and
`FitUserCustomizablePolynomial.py`, and within each file the rank-selected,
rank-unselected, and no-rank branches differ only in the leading bool. Now that
only the bool differs (the rgb→bool change made them alignable), the whole
method collapses to: compute `is_selected` once per cell, then run a single
4-way builder. A shared `_build_3d_color_list(self, selected_predicate)` on
`FittingBaseClass` would cut ~3 near-identical copies per file. No 3D builder
test exists (tests are 2D-only), so add 3D coverage alongside.

**4. Altitude: selections only sync to hidden inputs at Submit-button click.**
The picker holds selection state in the `selected` CSS class and reconciles it
to the hidden `polyFunctional_*`/`polyRational_*` inputs via `readPolyFlags()`,
which is wired only to the Submit button's `onClick`
(`equation_fit_interface.html:136`). Any submit path that bypasses that button
— pressing Enter in a text field (e.g. a data-name input), or a future
programmatic `form.submit()` — ships every hidden input at its default `False`,
silently discarding the user's coefficient selections. This is pre-existing
(identical on `main`), but the deeper fix doubles as a cleanup: have
`setSelected()` also write the corresponding hidden input at click time (the
cell id already encodes the field name), making the form always submit-ready
and letting `readPolyFlags()` + the inline `onClick` sweep be deleted entirely.

**Not in scope of the JS-modernization branch.** That branch delivered the
eval/dead-browser-branch removal and the inline-style→CSS-class migration, all
manually verified. These four are cleanup/altitude on the same surface; doing
them in-branch would invalidate that verification and expand the diff well past
its stated scope. Each wants its own focused commit + a fresh click-through.

## Verify Caddy deployment recipes on macOS and Linux

**Symptom / exposure.** As of 2026-04-30, `docs/deployment/macos.md`
and `docs/deployment/linux.md` describe Caddy + Waitress deployment
recipes (replacing the prior nginx-on-Linux/macOS + IIS-on-Windows
recipes per commit `dc49398` "Merge caddy-deployment"). Verification
status:

- **Linux** — written by structural extension from Caddy's
  documentation plus the prior nginx-based knowledge. Not
  exercised in production. No verification banner currently in the
  file.
- **macOS** — flagged in the file itself ("Verification status:
  Author had no Mac hardware available during the April 2026
  cross-platform migration. Verify on a real macOS box before
  relying on this recipe."). The Waitress launchd plist + Caddy
  commands are written by structural extension from the Linux
  recipe.
- **Windows** — tested on Windows 11 Pro during the April 2026
  cross-platform migration. `scripts/smoke_test.py` end-to-end test
  passes on this stack.

**Why it's worth verifying.** Production deployment fidelity. Anyone
following the macOS or Linux recipes for the first time might hit:

- Wrong Caddy install command (homebrew vs apt vs binary download).
- Wrong service-supervision behavior (systemd vs launchd vs NSSM).
- Wrong filesystem paths (`/usr/local/var/zunzun-ng/` on macOS,
  `/var/www/zunzun-ng/` on Linux, both untested).
- Wrong file permissions (`chown www-data` on Linux).
- Caddy auto-HTTPS quirks specific to the platform (firewall config,
  hostname resolution, port 80/443 reachability, Let's Encrypt rate
  limits during testing).

**Where to pick up.**

1. **Linux verification:** spin up an Ubuntu 22.04 / 24.04 VM (or a
   clean container with systemd). Follow `docs/deployment/linux.md`
   step by step. Note any commands that fail or produce different
   output than expected. Update the recipe with corrections.
   Add a verification banner to the top of the file once it works
   end-to-end.
2. **macOS verification:** find a macOS box (developer machine, CI
   runner, etc.). Follow `docs/deployment/macos.md`. Verify
   `brew install caddy`, the launchd plist loads, and the smoke
   test passes against a Caddy-fronted Waitress. Update the
   verification banner from "unverified" to a tested-on-X note.
3. **Optional: add a CI matrix job** that runs Caddy + smoke on
   each platform. CI currently runs pytest+smoke on Linux, macOS,
   Windows but doesn't exercise the deployment recipes (Caddy
   isn't installed in the CI environment).

**Not in scope of any current branch.** Documentation-quality
issue; the site is functional and deployable on Windows. Linux
deployments are likely fine in practice (the recipe is mostly
boilerplate plus Caddy's well-documented setup). macOS is a
genuine unknown until exercised.

## ~~Split the LRP status session blob into per-field rows~~ RESOLVED 2026-05-30

> **Resolution.** Replaced the shared status session blob with a
> per-dispatch `LRPStatus` ORM row (`zunzun/models.py`). Spec:
> `docs/superpowers/specs/2026-05-29-lrp-status-table-design.md`; plan:
> `docs/superpowers/plans/2026-05-29-lrp-status-table.md` (both local /
> gitignored per repo convention). Landed on `feat/lrp-status-table`
> as 9 commits; pytest 147/147, smoke 14/14, `migrate` creates
> `zunzun_lrpstatus`.
>
> **As-built design (deviates from the sketch below — the sketch was
> directional, not literal):**
> - **Row per DISPATCH, not per session_key.** The autopk `id` is the
>   dispatch identity; the current dispatch's pk lives in
>   `request.session["lrp_status_pk"]` and `StatusView` follows that
>   pointer. This eliminates the shared mutable cell entirely (each fit
>   writes only its own row), so the race dissolves rather than being
>   made atomic. The sketch's "`session_key` as PK" would have kept one
>   reused row per user and still needed an ownership guard.
> - **`dispatch_id` was NOT dropped — it was replaced by the row pk.**
>   `ChildPayload.dispatch_id: float` → `status_row_pk: int`. Ownership
>   identity is now row identity; `_we_own_status_slot()` and
>   `_publish_terminal_error()` were deleted, and `dispatched_at` is gone.
> - **Writes:** `update_status(**fields)` — an unconditional single-row
>   `LRPStatus.objects.filter(pk=...).update(...)` (no ownership check).
>   **Reads:** `get_status(field, default)`.
> - **Gate completion signal:** an explicit `completed` boolean
>   (`is_pending` checks `not row.completed`). An earlier cut reused
>   `redirect_to_results` as the signal, but `StatusView` clears that on
>   serve, which re-opened the pending window for fast fits — caught in
>   the final code review.
> - **The retry loop did NOT "collapse to Django's own retry"** (the
>   sketch's step 2 was wrong — Django doesn't auto-retry SQLite
>   `OperationalError`). The existing 5 s SQLite `busy_timeout`
>   (`DATABASES OPTIONS timeout`) covers `LRPStatus` writes; no manual
>   retry was added. `data`/`functionfinder` keep `save_with_retry` /
>   `load_with_retry`.
> - **Lifecycle:** parent deletes the prior row on each dispatch +
>   the housekeeping child sweeps rows older than `SESSION_COOKIE_AGE`.
> - **`data` / `functionfinder` stores unchanged** (still JSON blobs via
>   `NumpySessionSerializer`).
>
> **Two bugs the review/smoke gate caught (both fixed on-branch):**
> (1) per-user cap weakened because the new row defaulted
> `last_status_check=0.0` → now stamped at dispatch; (2) the `completed`
> column was added by *regenerating* `0001` (a no-op `migrate` on
> already-applied DBs) → corrected to an append-only `0002` migration.
> See [[migrations-and-smoke-real-db]] for the latter lesson.
>
> Historical notes below, preserved for reference.

**Symptom / exposure.** The LRP status session is a single Django
session blob (JSON-encoded dict) that the parent and child processes
both read-modify-write. Every shared-session race the
`fix/pipeline-error-redirects` branch hunted across 11 Codex rounds
and several self-review passes traces back to this one structural
constraint: when the parent's `SetInitialStatusDataIntoSessionVariables`
overwrites `dispatched_at` while a child is mid-render, or when an
older child publishes its terminal redirect during the window between
a newer child's check and its write, the underlying problem is that
"check ownership then write" cannot be atomic against a JSON blob
serialized as one column. The PR shipped a dispatch-id ownership
protocol (`_we_own_status_slot()`, gated bundled writes via
`_publish_terminal_error()`) that narrows every race window but does
not close them — see Codex's round-12 P2 comment on
`StatusMonitoredLongRunningProcessPage.py` ("TOCTOU between ownership
check and write") and the reply at
[PR #11 thread](https://github.com/kiloscheffer/zunzun-ng/pull/11#discussion_r3321258888)
acknowledging the constraint.

**Why it's worth fixing.** Codex's original review-1 finding #1
("lost-update race in status sessions can drop completion redirects")
called this out as the deep fix in May 2026. Sixteen commits, three
new helpers, and ~600 lines of inline race-condition rationale later,
the dispatch-id workaround is structurally correct but architecturally
narrow — every new shared-session writer must remember to call the
helper, and every new race window narrows the constraint without
closing it. A per-field schema with `QuerySet.filter(...).update()`
for race-free single-field updates would eliminate the ownership
check at every call site, the helper's defensive `return True` on
read failure, and the bundled-write pattern entirely.

**Where to pick up.**

1. Design a small ORM model (e.g., `LRPStatus(session_key, processID,
   dispatched_at, current_status, redirect_to_results, parallel_process_count,
   last_status_check, start_time)` with `session_key` as primary key).
   The status data currently in the JSON blob maps 1:1 to columns.
2. Change `SaveDictionaryOfItemsToSessionStore("status", {...})` to
   `LRPStatus.objects.filter(session_key=...).update(**fields)` — a
   single SQL UPDATE per call. The 100-retry session-lock loop
   collapses to Django ORM's own retry on `OperationalError`.
3. Change `LoadItemFromSessionStore("status", key)` to
   `LRPStatus.objects.filter(session_key=...).values_list(key, flat=True).first()`.
4. Drop `_we_own_status_slot()`, `_publish_terminal_error()`, the
   `dispatch_id` field on `ChildPayload`, and the entire dispatch-id
   ownership protocol — atomic single-field updates make ownership
   identity unnecessary.
5. The session-key plumbing stays (`session_key_status`,
   `session_key_data`, `session_key_functionfinder`) since
   `data` and `functionfinder` sessions are still JSON blobs by nature
   (they hold equation/spline state, not race-sensitive flags).

**Not in scope of any current branch.** Substantial change across
the LRP base class, every subclass that touches `SaveDictionaryOfItemsToSessionStore("status", ...)`,
and the `fork-pattern-reviewer` agent's checks. Worth doing as a
focused PR after the current branch ships, so the diff is bounded
to "swap blob for table" without the in-flight race-condition fixes
muddying the picture.

## ~~Make LRPStatus completion signal uniform across the views~~ RESOLVED 2026-05-31

> **Resolution.** The core work landed on the same `feat/lrp-status-table`
> branch (later commits than the cut that prompted this entry), so the
> symptom described below — "the two polling views still key completion on
> `redirect_to_results`" — is **no longer true on the branch**. Final state:
> - `StatusUpdateView` reports `{"completed": True}` on
>   `row.completed or row.redirect_to_results` (`zunzun/views.py`) — the
>   durable `completed` flag is the primary signal; the redirect arm just
>   covers the window before `StatusView` serves it.
> - `StatusView` branches on `row.completed`: serves the file/302 when
>   `redirect_to_results` is set, else renders a terminal "no results"
>   page instead of looping on the in-progress template.
> - Both edge cases are closed and tested:
>   `test_status_view.py::test_status_view_serves_terminal_page_when_completed_without_redirect`
>   (disk-unwritable terminal) and
>   `test_status_update_returns_completed_when_completed_flag_set_without_redirect`
>   (poll-after-clear).
> - A reader-side **dead-pid backstop** (`_finalize_row_if_child_dead` in
>   `zunzun/views.py`, `platform_compat.pid_is_alive`) was added in the
>   PR #21 review pass to cover the remaining gap the `completed` flag
>   can't: a child that dies WITHOUT finalizing its row at all (SIGKILL /
>   OOM / segfault, or a terminal `update_status` that itself failed under
>   DB lock past `busy_timeout`). The views detect the owning pid is gone
>   and mark the row terminal so the poll ends.
>
> **Backstop hardening (`/code-review xhigh`, 2026-05-31).** Three follow-up
> fixes from a later review pass, all in `zunzun/views.py` /
> `_finalize_row_if_child_dead`:
> - **Pre-pid-write death.** The backstop early-returned on `process_id == 0`,
>   so a child that died (or failed to spawn) BEFORE `PerformAllWork`'s first
>   `process_id` write left the row stuck — there was no pid to probe. It now
>   finalizes a `process_id == 0` row once it is past the 60s pending window
>   (by `start_time` age; no probe), matching `is_pending`'s bound. Covered by
>   `test_status_view.py::test_backstop_finalizes_unset_pid_row_past_pending_window`.
> - **Completed-but-uncleared gate block.** The per-user gate's `is_active`
>   now also requires `not row.completed`, so a fit that finished but whose
>   child died in the window before clearing `process_id` (result already
>   deliverable) no longer falsely blocks the next POST.
> - **Gate now applies the backstop.** `LongRunningProcessView`'s per-user
>   gate calls `_finalize_row_if_child_dead(row)` before computing
>   `is_active` / `is_pending`. Previously the gate trusted the heartbeat
>   alone, so a SIGKILL/OOM-killed child blocked the user's retry for up to
>   300s (the poll views already recovered; the gate was the one place a
>   provably-dead fit still gated). A live fit's pid passes the probe and is
>   left untouched. Covered by
>   `test_views_per_user_cap.py::test_concurrent_fit_allowed_when_pid_dead`.
>
> **Still open (separable polish, not blockers).** The "Related minor
> cleanups" below remain deferred: the duplicated terminal-write tuple
> across ~5 sites is folded into the "Model LRPStatus lifecycle as an
> explicit state field" entry; the `CheckIfStillUsed` fallback-masking note
> and the `StatusView`/`StatusUpdateView`/`CheckIfStillUsed` over-fetch are
> small standalone items worth a future sweep.

**Symptom / exposure.** Follow-up from the `/code-review` of the
LRP-status-table branch (`feat/lrp-status-table`, 2026-05-30). The
branch added a durable `completed` boolean to `LRPStatus` and the
per-user gate + `_run_fit_child`'s terminal handler key on it. But the
two polling views still key completion on `redirect_to_results`:
- `StatusView` (`zunzun/views.py`) serves the result file/302 iff
  `row.redirect_to_results` is truthy, and CLEARS it to `""` on serve.
- `StatusUpdateView` reports `{"completed": True}` iff
  `row.redirect_to_results` is truthy.

This is behavior-preserved from `main` (the JS-poll redesign always
keyed on the redirect), so it's not a regression, and the normal
single-tab flow works (smoke 14/14). But two edge cases are now
needlessly fragile given `completed` exists:
1. **Multi-viewer / poll-after-clear.** If one viewer completes and
   `StatusView` clears the redirect, a second concurrent poller (other
   tab, or an in-flight request) sees `redirect_to_results == ""` →
   `StatusUpdateView` returns `{"completed": False}` → that viewer
   polls forever.
2. **Disk-unwritable terminal error.** When `_write_terminal_error_html`
   returns `None` (disk full / permission denied), the terminal write
   sets `completed=True, process_id=0` but leaves `redirect_to_results
   == ""`. Both views then never signal completion → stuck poll.

**Why it's worth fixing.** `completed` is the durable done-signal;
`redirect_to_results` is an ephemeral payload that `StatusView`
consumes. Keying completion on the payload is the same overloaded-signal
mistake the gate fix already corrected on its side.

**Where to pick up (coordinate BOTH views — do not change one alone).**
A naive `if row.redirect_to_results or row.completed:` in
`StatusUpdateView` ALONE causes a navigation loop: the JS navigates to
`StatusView`, which (still keying on the now-empty redirect) re-renders
the in-progress page, whose poller immediately re-completes. The fix
must move both views to the `completed` flag together:
1. `StatusUpdateView`: report completion on `row.completed` (not the
   redirect).
2. `StatusView`: branch on `row.completed`. If completed AND
   `redirect_to_results` is set → serve/redirect as today (and the
   clear is fine). If completed AND redirect is `""` (already served,
   or disk-failure terminal) → render a terminal "your fit finished —
   no result is available / it has already been shown" page, NOT the
   in-progress template (which would loop).
3. Add tests: a poll after `StatusView` consumed the redirect returns
   completed; the disk-failure terminal (completed, empty redirect)
   lands on a terminal page, not an infinite poll.

**Related minor cleanups surfaced in the same review (fold in or skip):**
- The terminal-error write
  `update_status(redirect_to_results=self._write_terminal_error_html(msg)
  or "", process_id=0, completed=True, current_status=msg,
  parallel_count=0)` is duplicated across ~5 sites (FittingBaseClass,
  FitUserDefinedFunction, FunctionFinder ×2, StatisticalDistributions,
  base). The deleted `_publish_terminal_error()` used to be the
  chokepoint; consider a small `_publish_terminal_error(html_path)`-style
  helper again so a future terminal site can't forget `completed=True`
  / `process_id=0`. The `test_all_broken_process_pool_sites_use_terminal_helpers`
  structural test only checks `update_status` + `_write_terminal_error_html`
  presence, not that `process_id=0` / `completed=True` are passed.
- `CheckIfStillUsed`'s `get_status("last_status_check") or ... or
  time.time()` fallback masks the never-stamped case that
  `LongRunningProcessView` now prevents at dispatch — harmless defense
  today, but it would hide a future regression rather than surface it.
- Minor over-fetch: `StatusView`/`StatusUpdateView` fetch the full row
  (`.first()`) but read a subset; `CheckIfStillUsed` issues two
  `get_status` SELECTs (1 Hz hot path) where one `.values(a, b)` would
  do.

**Not in scope of the LRP-status-table branch.** That branch's job was
the blob→row cutover and closing the ownership race; it preserved the
existing (main) completion-signal behavior. Tightening the
completion signal onto `completed` is separable polish.

## ~~Model LRPStatus lifecycle as an explicit state field~~ RESOLVED 2026-05-31

> **Resolution.** A `state` `TextChoices` field (`INITIALIZING` / `RUNNING` /
> `TERMINAL`, default `INITIALIZING`) replaced the derived `completed` boolean.
> Two classmethods centralize the lifecycle tuple on `LRPStatus`: `mark_running(pk,
> pid)` (INITIALIZING → RUNNING) and `mark_terminal(pk, ...)` (→ TERMINAL, always
> sets `state=TERMINAL` + `process_id=0` atomically; optional `redirect` /
> `current_status` / `parallel_count` written only when passed). The per-user gate
> (`is_active` reads `state == RUNNING` + heartbeat; `is_pending` reads
> `state == INITIALIZING` + 60s start-time window), `StatusView`, `StatusUpdateView`,
> and the `_finalize_row_if_child_dead` backstop all read `state`. The
> `PerformAllWork` `finally` stays non-terminal by design so `_run_fit_child`'s
> exception handler can still publish the error redirect without clobbering a
> served success. Two append-only migrations: `0004_lrpstatus_state` (add `state` +
> backfill from `completed`) and `0005_remove_lrpstatus_completed` (remove
> `completed`). The two source-inspection structural guards now assert
> `mark_terminal`, backed by new behavioral tests on the classmethods.
> Design: `docs/superpowers/specs/2026-05-31-lrpstatus-state-field-design.md`;
> plan: `docs/superpowers/plans/2026-05-31-lrpstatus-state-field.md`.

**Symptom / exposure.** Type-design observation from the comprehensive PR
review of the LRP-status-table branch (`feat/lrp-status-table`, PR #21,
2026-05-30). `LRPStatus` is an anemic model: it has no behavior, and the
fit lifecycle (initializing → running → terminal) is not represented
directly — it's *reconstructed* from loose, individually-mutable fields
(`process_id`, `completed`, `redirect_to_results`, `last_status_check`).
The per-user gate in `LongRunningProcessView` derives `is_active` /
`is_pending` by combining 3–4 of these fields with two time windows, and
terminal consistency (`process_id=0` + `completed=True`, plus a redirect
or status text) is hand-maintained across ~8 write sites (PerformAllWork
success + finally, the base/FunctionFinder/StatisticalDistributions
BrokenProcessPool handlers, FittingBaseClass + FitUserDefinedFunction
Solve/stat-failure terminals, `_run_fit_child`'s except handler, and the
three success-path `RenderOutputHTML` redirect writes). Each new terminal
site has to remember the full tuple; the
`test_all_broken_process_pool_sites_use_terminal_helpers` /
`test_all_success_terminal_writes_set_completed` structural guards exist
precisely because the invariant is enforced by convention, not by type.

**Recommended improvement (deferred).** Add a Django `TextChoices`
`state` field (`INITIALIZING` / `RUNNING` / `TERMINAL`, default
`INITIALIZING`) and 2–3 transition methods on the model —
`mark_running(pid)`, `mark_terminal(redirect="")` (and the gate reads
`row.state` directly). The transition methods become the single place
that sets the field tuple correctly, replacing the derived `completed`
flag and the scattered `process_id=0, completed=True` pairs. The gate's
`is_active` / `is_pending` collapse to `state == RUNNING` (+ heartbeat
window) and `state == INITIALIZING` (+ pending window). This is an
**additive migration** (a new column + a data-free default), so it
doesn't churn the schema history. Not an idealized rewrite — the current
field-based design works, is covered by the gate/terminal tests, and
ships green (147 unit + 14 smoke); this is separable type-design polish,
sequence it with or after the "Make LRPStatus completion signal uniform"
entry above (they touch the same fields).

**Behavior change to revisit (concurrent-fit config).** The
delete-prior-row step in `LongRunningProcessView` fires ONLY when
`ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=False` (concurrent DISALLOWED);
see commit `92c6075`. The two modes diverge:

- **Disallowed (`=False`, production-recommended).** Reaching the
  create/delete block means the per-user gate already judged the prior fit
  stale or completed, so the new dispatch deletes the prior row. A still-
  running superseded child then reads `process_id is None` in
  `CheckIfStillUsed` and *does* reap itself — `_teardown_abandoned_fit()` +
  `_ReportsPipelineAborted` at its next heartbeat — freeing CPU/RAM
  immediately rather than running to natural completion.
- **Allowed (`=True`, the dev default).** The prior row is deliberately
  NOT deleted (that would tear down a fit the setting promises to keep
  running). The older fit keeps its own row, so its `CheckIfStillUsed`
  never sees a missing row and runs to completion; the orphaned prior row
  is reclaimed by the housekeeping age-sweep once the session pointer moves
  on.

This is a behavior change from `main`, where the single shared status slot
let a newer fit's `processID` signal an older child to tear down
regardless of the concurrent-fit setting. Revisit if concurrent-fit
resource use under `=True` (an abandoned older fit consuming CPU/RAM until
it finishes) becomes a concern — e.g. keep superseded rows briefly with a
`superseded` state instead of leaving them for the age-sweep, so
`CheckIfStillUsed` can reap them in allow-concurrent mode too.

## ~~Replace eval() with getattr() in LRP session helpers~~ RESOLVED 2026-05-29

> **Resolution.** Replaced the four `eval()` calls in
> `SaveDictionaryOfItemsToSessionStore` and `LoadItemFromSessionStore`
> with `getattr(self, "session_" + name)` and
> `SessionStore(getattr(self, "session_key_" + name))` respectively.
> Also dropped the now-stale
> `# pyright: ignore[reportUnusedImport]` on the `SessionStore`
> import — that workaround was only needed while the symbol was
> referenced via an `eval()` string. Pytest 133/133 green. Did not
> add the optional parametrized-over-three-names test the entry
> suggested — `getattr(self, "session_" + name)` is semantically
> identical for any valid attribute name by Python guarantee, and
> the existing roundtrip test on `"status"` plus visual inspection
> covers the substitution.
>
> **Out of scope of this PR**, eight other `eval()` calls remain in
> the same file — tracked separately in the new "Replace remaining
> eval() calls in StatusMonitoredLongRunningProcessPage" entry below.
>
> Historical notes below, preserved for reference.

**Symptom / exposure.** `StatusMonitoredLongRunningProcessPage.py`'s
session helpers use `eval()` to construct attribute lookups by name:

```python
session = eval("self.session_" + inSessionStoreName)
session = eval("SessionStore(self.session_key_" + inSessionStoreName + ")")
```

at four sites in `SaveDictionaryOfItemsToSessionStore` and
`LoadItemFromSessionStore`. The arguments are always one of three
fixed literals (`"status"`, `"data"`, `"functionfinder"`) so the
calls aren't an injection vector, but `eval()` is a code-review red
flag wherever it appears and complicates future static analysis.

**Why it's worth fixing.** Mechanical, low-risk, removes four
`eval()` calls. The simplifier agent's medium-precision review
flagged it but recommended a separate PR ("bundling unrelated
cleanup into a fix PR muddles the bisect/revert story"). Worth a
focused commit when convenient.

**Where to pick up.**

1. Replace `eval("self.session_" + inSessionStoreName)` with
   `getattr(self, "session_" + inSessionStoreName)` at both sites.
2. Replace `eval("SessionStore(self.session_key_" + inSessionStoreName + ")")`
   with `SessionStore(getattr(self, "session_key_" + inSessionStoreName))`
   at both sites.
3. Add a test verifying all three store names still resolve. Tests
   under `tests/test_session_roundtrip.py` already exercise the
   round-trip; verify they still pass with the substitution.

**Not in scope of any current branch.** Pure refactor; no behavior
change. Worth a small focused commit when convenient.

## ~~Replace remaining eval() calls in StatusMonitoredLongRunningProcessPage~~ RESOLVED 2026-05-29

> **Resolution.** All three patterns substituted in one focused commit:
>
> - 4 `dataObject` attribute reads (lines 101, 106, 138, 143):
>   `eval("inReportObject.dataObject." + str(item))` →
>   `getattr(inReportObject.dataObject, item)`. Single `replace_all` edit.
> - 3 form-class instantiations (lines 1315, 1420, 1450):
>   `eval("zunzun.forms.<Form>_" + str(self.dimensionality) + "D(...)")` →
>   `getattr(zunzun.forms, "<Form>_" + str(self.dimensionality) + "D")(...)`.
> - 1 defaultData read (line 1433):
>   `eval("self.defaultData" + str(self.dimensionality) + "D")` →
>   `getattr(self, "defaultData" + str(self.dimensionality) + "D")`.
>
> `eval()` count in `StatusMonitoredLongRunningProcessPage.py` is now
> zero. Pytest 133/133 green. Did NOT factor the two near-duplicate
> `dataObject`-dir-loop blocks into a single helper — that scope was
> explicitly left to author judgment in the entry and would have
> muddied the substitution PR. Worth a separate small refactor when
> convenient.
>
> Historical notes below, preserved for reference.

**Symptom / exposure.** After the session-helper `eval()` cleanup
landed (resolved entry above), eight `eval()` calls remain in
`StatusMonitoredLongRunningProcessPage.py`. They fall into three
patterns, each mechanically replaceable:

1. **Dynamic attribute reads on `inReportObject.dataObject` (4 sites,
   lines 101, 106, 138, 143).** Inside two near-identical loops over
   `dir(inReportObject.dataObject)`:

   ```python
   if -1 != str(eval("inReportObject.dataObject." + str(item))).find("bound"):
       continue
   s += str(item) + ": " + str(eval("inReportObject.dataObject." + str(item))) + "\n\n"
   ```

   Direct replacement: `getattr(inReportObject.dataObject, item)`. The
   two loops are themselves a duplicated block that could be factored
   into a single helper; doing so removes 2 of the 4 sites for free.

2. **Form-class instantiation by dimensionality (3 sites, lines 1315,
   1420, 1450).** Each picks a Django form class by name:

   ```python
   itemsToRender["EvaluateAtAPointForm"] = eval(
       "zunzun.forms.EvaluateAtAPointForm_" + str(self.dimensionality) + "D()"
   )
   self.unboundForm = eval(
       "zunzun.forms.CharacterizeDataForm_" + str(self.dimensionality) + "D()"
   )
   self.boundForm = eval(
       "zunzun.forms.CharacterizeDataForm_" + str(self.dimensionality) + "D(request.POST)"
   )
   ```

   Replacement: `getattr(zunzun.forms, name)(...)` where name is the
   concatenated string. The forms module defines a fixed set of
   `*_2D` / `*_3D` classes — no injection vector, just dynamic dispatch.

3. **Dynamic attribute read on self by dimensionality (1 site, line
   1433).** `eval("self.defaultData" + str(self.dimensionality) + "D")`
   selects between `self.defaultData2D` and `self.defaultData3D`.
   Replacement: `getattr(self, "defaultData" + str(self.dimensionality) + "D")`.

**Why it's worth fixing.** Same reasoning as the resolved
session-helper entry above: mechanical, low-risk, removes code-review
red flags. Doing all eight in one focused commit collapses the
"eval() in StatusMonitoredLongRunningProcessPage.py" surface to zero.

**Where to pick up.**

1. Apply the three patterns above. Line numbers will shift slightly
   between now and pickup; grep for `eval\\(` in the file and verify
   exactly eight matches remain to scope the work.
2. The two `dataObject`-dir-loop blocks (around lines 96-110 and
   132-145) are near-duplicates and a candidate for factoring
   into a single helper (e.g.,
   `_dataObject_summary_text(inReportObject)`); leave that to a
   judgment call by the author — pure substitution without
   refactor is fine if scope creep is a concern.
3. `zunzun/forms.py` should be inspected to confirm the
   `EvaluateAtAPointForm_2D` / `EvaluateAtAPointForm_3D` and
   `CharacterizeDataForm_2D` / `CharacterizeDataForm_3D` symbols
   are all bound at import time (they should be — they're
   class definitions).
4. Verification: existing pytest suite covers the dispatch
   indirectly (form-bound views are exercised by smoke); a clean
   pytest + smoke pass is sufficient.

**Not in scope of any current branch.** Pure refactor; no behavior
change. Worth a small focused commit when convenient.

## ~~Test coverage for dispatch-ownership and terminal-error helpers~~ RESOLVED 2026-05-29

> **Resolution.** Eight tests added to
> `tests/test_perform_all_work_pipeline.py` covering gaps 1–4
> (pytest now 143, was 135):
>
> - **`_we_own_status_slot()`** — three branch tests: pid+dispatch
>   match → True; pid match + dispatch mismatch → False; session read
>   raises `OperationalError` → True (with `caplog` assertion on the
>   "Ownership check session read failed" log). The
>   `OperationalError`-subclass-of-`DatabaseError` relationship is what
>   makes it land in the `except (DatabaseError, InterfaceError)` branch.
> - **`_write_terminal_error_html()`** — success path returns the
>   artifact path and writes a non-empty file; disk-failure path
>   (`page_artifact_path` → a path inside a nonexistent dir, so both
>   the template render AND the hardcoded fallback `open()` fail)
>   returns None without raising.
> - **BrokenProcessPool publish** — one integration test on
>   `CreateOutputReportsInParallelUsingProcessPool`: mocks
>   `fit_pool.submit_many` to raise `BrokenProcessPool`, asserts
>   `_ReportsPipelineAborted` is raised AND a single bundled
>   ownership-gated write carries
>   `redirectToResultsFileOrURL` + `processID:0` + `dispatched_at:0` +
>   `currentStatus`. Plus a structural test asserting all four
>   BrokenProcessPool sites (StatusMonitored base +
>   `FunctionFinder.PerformWorkInParallel` ×2 +
>   `StatisticalDistributions.PerformWorkInParallel`) route through
>   `_publish_terminal_error` + `_write_terminal_error_html` — keyed on
>   the `_write_terminal_error_html` caller set, which isolates the
>   pool-death cohort from the Solve-failure paths (`FittingBaseClass`,
>   `FitUserDefinedFunction`) that use a different terminal template.
> - **Success-path entry gate** — asserts
>   `RenderOutputHTMLToAFileAndSetStatusRedirect` returns before ANY
>   shared-session write when a newer dispatch owns the slot (the
>   original race; smoke runs one fit at a time so can't catch it).
>
> **Gap 5 (optional failure-path smoke scenario) deferred** — see the
> new "Failure-path smoke scenario for the abort pipeline" entry
> below. Kept this PR a focused pure-test-unit addition; the smoke
> scenario adds Waitress+spawn runtime and is separable.
>
> Historical notes below, preserved for reference.

**Symptom / exposure.** The `fix/pipeline-error-redirects` branch
landed three new helpers on `StatusMonitoredLongRunningProcessPage`
that ~8 call sites depend on for race-free terminal writes:
`_we_own_status_slot()`, `_write_terminal_error_html()`, and
`_publish_terminal_error()`. The pr-test-analyzer agent's review
([5-agent review PR comment](https://github.com/kiloscheffer/zunzun-ng/pull/11#issuecomment-4572150311))
identified three coverage gaps that survive the PR:

1. **`_we_own_status_slot()` is never tested as a unit.** All
   ~8 callers exercise it transitively but the load-bearing
   "return True on session-read failure" branch — documented
   explicitly in the helper's docstring as a trade-off — has zero
   coverage. The exact one-line conditional that gets "cleaned up"
   in a future refactor with no warning.
2. **`_write_terminal_error_html()`'s None-on-disk-failure path**
   is uncovered. All four BrokenProcessPool sites guard with
   `if error_html_path:`; if the helper regressed to raise instead
   of return None, the BrokenProcessPool handler would crash inside
   its own exception handler.
3. **The 4 BrokenProcessPool sites' new terminal redirect
   publication is not tested directly.** Each site could regress
   to the pre-fix two-call shape (drop redirect on
   `_we_own_status_slot` False) and the UI-stuck-bug class would
   return with zero test signal. `_ReportsPipelineAborted` is
   asserted on existing tests but the bundled redirect-bearing save
   is not.
4. **Success-path ownership check at `RenderOutputHTML:1241`** has
   no test. A refactor that drops the gate would silently re-introduce
   the original race; smoke runs one fit at a time so wouldn't catch.

A fifth gap (failure-path smoke scenario) is folded in here for
convenience.

**Why it's worth fixing.** The PR's contracts are now well-documented
in commit messages and inline comments, but tests are the only thing
that catches a regression at PR-review time. The unit cost for each
of these is ~10 lines using the existing `_build_fake_lrp_module`
harness in `tests/test_child_payload.py`.

**Where to pick up.**

1. **`_we_own_status_slot()` unit tests** in `tests/test_perform_all_work_pipeline.py`:
   one test per branch — pid match + dispatched_at match → True; pid
   match + dispatched_at mismatch → False; session read raises
   `OperationalError` → True (with caplog assertion).
2. **`_write_terminal_error_html()` unit tests**: success path returns
   path and the file exists; disk failure (point `page_artifact_path`
   at `/dev/this/path/does/not/exist/x.html`) returns None without
   raising.
3. **One BrokenProcessPool integration test**: mock
   `ProcessPoolExecutor` to raise `BrokenProcessPool`, call
   `CreateOutputReportsInParallelUsingProcessPool`, assert
   `_ReportsPipelineAborted` raised AND the bundled save included
   `redirectToResultsFileOrURL`/`processID:0`/`dispatched_at:0`.
   FunctionFinder and StatisticalDistributions are near-duplicates;
   one site test plus a structural assertion that all four use
   `_we_own_status_slot()` + `_write_terminal_error_html()` is
   reasonable cost/benefit.
4. **Success-path ownership test**: mock `LoadItemFromSessionStore`
   to return a newer-dispatch value; call
   `RenderOutputHTMLToAFileAndSetStatusRedirect`; assert no
   `SaveDictionaryOfItemsToSessionStore` was called and the result
   file IS still on disk (harmless leftover).
5. **Optional failure-path smoke scenario** in `scripts/smoke_test.py`:
   POST a UDF with a deliberately bad formula (e.g., `1/(X-X)`) to
   trigger Solve failure; poll status; assert the polling UI lands
   on the `exception_while_fitting_an_equation.html` template within
   a bounded timeout. Costs ~30 s extra on Windows but exercises the
   real Waitress + spawn + session pipeline end-to-end.

**Not in scope of any current branch.** Pure test addition; no
behavior change. Worth a focused PR (`test: cover dispatch-ownership
helpers and BrokenProcessPool redirects`) so the diff is easy to
review and bisect.

## ~~Failure-path smoke scenario for the abort pipeline~~ RESOLVED 2026-05-29

> **Resolution — built as a pytest, not a smoke scenario, after two
> findings made the original "POST a bad UDF to Waitress" plan
> impractical.**
>
> Added `test_run_fit_child_publishes_terminal_redirect_to_a_real_session`
> to `tests/test_child_payload.py` (pytest 144, was 143). A
> `FailingLRP` that subclasses `StatusMonitoredLongRunningProcessPage`
> (inheriting the genuine `LoadItemFromSessionStore` /
> `SaveDictionaryOfItemsToSessionStore`) is driven through the real
> `_run_fit_child` entrypoint against a real `SessionStore`; its
> `PerformAllWork` raises to simulate a post-dispatch fit failure. The
> test reloads the status session from its key and asserts the terminal
> redirect persisted through the genuine serialize → SQLite →
> deserialize path, the error artifact exists on disk, and the
> ownership-gated bundled write cleared `processID` / `dispatched_at`.
> This adds the real-session round-trip the sibling FakeLRP tests
> (mocked saves) lack.
>
> **Finding 1 — pyeq3 is hardened against bad fits, so a "bad formula"
> can't reliably reach the exception template.**
> `IModel.CalculateReducedDataFittingTarget` wraps the whole model
> eval in `try/except Exception: return 1.0e300` and also maps
> non-finite SSQ to `1.0e300`, so the differential-evolution phase
> swallows every exception and every inf/NaN. A degenerate UDF
> (`a*log(X-100)`, all-NaN predictions) doesn't crash — DE picks the
> least-bad coefficient vector and the fit produces a *garbage success
> page*. Symbolic-divide formulas (`a/(X-X)`) are rejected at parse
> time, and `ConvertStringIntsToStringFloats` mangles index tricks
> (`X[100]` → `X[100.0]`). The only unsanitized path is the post-DE
> `curve_fit` refinement, which can't be steered into raising from form
> input. So the abort/terminal pipeline can't be reached deterministically
> through the HTTP fit form.
>
> **Finding 2 — a true os-level spawn can't be used in a pytest here.**
> A spawned child is a fresh interpreter that (a) can't see a
> parent-process monkeypatch (so "monkeypatch Solve" is impossible
> across the boundary) and (b) uses the production `session_db`, not
> pytest-django's transaction-scoped test session DB — so the
> session-redirect write would be invisible to the parent's test
> connection. Driving the real `_run_fit_child` in-process against a
> real session is the faithful, deterministic substitute; cross-process
> pickling is already covered by `test_pickle_spike.py` and the
> `ChildPayload` round-trip tests.
>
> Historical notes below, preserved for reference.

**Symptom / exposure.** Gap 5 of the (now-resolved) "Test coverage
for dispatch-ownership and terminal-error helpers" entry above. The
unit + integration tests added 2026-05-29 cover the helper contracts
in isolation, but no smoke scenario exercises the *failure* path
end-to-end through the real Waitress + spawn + session pipeline.
Every existing smoke scenario drives a fit that succeeds; the
terminal-error redirect (the thing PR #11 was built to make
race-free) is never walked under a real cross-process run.

**Why it's worth fixing.** The unit tests mock `LoadItemFromSessionStore`
/ `SaveDictionaryOfItemsToSessionStore` and the pool. A smoke
scenario would prove the genuine article: a child hitting a Solve
failure actually writes `exception_while_fitting_an_equation.html`,
publishes the redirect into the real SQLite session, and the polling
UI lands on it — across the process boundary the unit tests stub out.
Mirrors the value the spline/UDF round-trip scenarios add over their
unit-test counterparts.

**Where to pick up.**

1. Add a scenario to `scripts/smoke_test.py`: POST a UDF with a
   deliberately divergent / undefined formula (e.g. `1/(X-X)` so the
   Solve raises rather than the form rejecting it at validation) to
   `/FitUserDefinedFunction__F__/2/`.
2. Poll `/StatusAndResults/` until the REFRESH/REDIRECT settles.
3. Assert the result body matches the
   `exception_while_fitting_an_equation.html` markers within a bounded
   timeout (UDF Solve failures are fast — budget ~60 s on Windows,
   well under the 2D ceiling).
4. Verify the bad formula actually reaches `Solve()` rather than being
   rejected earlier by `Equation_2D.clean()` / form validation — if it
   short-circuits at validation, pick a formula that parses but
   diverges numerically so the failure happens in the fit child.

**Not in scope of the test-coverage PR.** That PR was deliberately a
pure unit/integration-test addition; the smoke scenario adds
Waitress+spawn runtime and a new POST fixture, so it's separable.

## ~~Robustness improvements in LRP child logging and session reads~~ RESOLVED 2026-05-29

> **Resolution.** Both halves addressed in the same PR as #1.
>
> **Read-side retry.** `load_with_retry(session, key, default=None)`
> in `zunzun/session_helpers.py` mirrors `save_with_retry`:
> 100 retries @ 10 Hz against transient `DatabaseError` /
> `InterfaceError` from the SQLite backend. `KeyError` returns the
> default immediately (no retry). `LoadItemFromSessionStore` in
> `StatusMonitoredLongRunningProcessPage` now delegates to it. The
> defensive "return True on read failure" in `_we_own_status_slot`
> stays as a last-resort net for the exhausted-retries case.
>
> **Centralized child logging.** The 21 inline
> `logging.basicConfig(filename=temp/{pid}.log, level=DEBUG)` calls
> across the LRP tree (10 in `StatusMonitoredLongRunningProcessPage`,
> 6 in `FunctionFinder`, 2 in `ReportsAndGraphs`, 1 each in
> `FunctionFinderResults` and `StatisticalDistributions`, plus 1 in
> `child_payload.py`'s except branch) were all deleted. They were
> already no-ops as of PR #16's `_setup_child_root_logging()` —
> root has the per-pid FileHandler attached at child startup, before
> any LRP code runs, so subsequent inline basicConfig calls saw a
> handler exist and skipped. The deletions remove the dead code
> AND the lingering "lowers root to DEBUG" behavior change that
> Codex flagged in PR #16's second review (each basicConfig call
> redundantly set root level to DEBUG).
>
> The `import logging` lines inside individual except clauses stay —
> they're still needed for `logging.exception(...)` calls. Future
> consolidation to module-level imports is a separate cosmetic pass.
>
> Did NOT add the optional `error_ids.py` registry that the entry
> suggested. That's a deeper observability improvement with its own
> design space; deferring as a separate item if there's appetite
> later.
>
> **Codex review on PR #17 caught a pool-worker gap in the first cut.**
> The deletions stripped `basicConfig(filename=temp/{pid}.log)` calls
> in code that runs inside `FitPool` workers (e.g., the
> `ParallelWorker_*` functions in `StatusMonitoredLongRunningProcessPage`,
> `parallelWorkFunction` / `serialWorker` in `FunctionFinder`, etc.).
> Pool workers are sub-children of the LRP child and DO NOT inherit
> its FileHandler — each is its own fresh spawn. After deletion, their
> `logging.exception(...)` calls fell back to stderr and the
> user-facing "see log file" message pointed at a file that didn't
> exist. Fixed by adding a default `_worker_initializer` to
> `zunzun/parallel_pool.py` that calls `_setup_child_root_logging()`
> on every pool worker at startup, then chains any caller-supplied
> initializer. The `FunctionFinder` callsite that passes
> `initializer=_install_worker_data_cache` continues to work — the
> wrapper runs logging setup first, then the caller's hook.
>
> Pytest 133/133 green.
>
> Historical notes below, preserved for reference.

**Symptom / exposure.** The silent-failure-hunter agent's review of
the `fix/pipeline-error-redirects` branch surfaced two correctness-
adjacent issues that were deferred because they touch broader
codebase patterns not introduced by this PR:

1. **`LoadItemFromSessionStore` has no retry loop.** Its sibling
   `SaveDictionaryOfItemsToSessionStore` already wraps `session.save()`
   in a 100-retry @ 10Hz loop because spawn-child contention on the
   SQLite session DB is common. The read path has zero retries: the
   first transient `OperationalError` (lock contention) or
   `InterfaceError` (connection already closed by a sibling call)
   raises out. `_we_own_status_slot()` now catches these and defaults
   "we own" (with logging), but the underlying transient is silently
   handled at the helper level rather than retried at the DB level.
   The 1-call `LoadItemFromSessionStore` shape means many call sites
   are similarly exposed — `CheckIfStillUsed`, the per-user gate
   checks in `views.py`, etc.

2. **`logging.basicConfig` is re-called at 20+ sites in the LRP
   tree.** Each site does
   `logging.basicConfig(filename=os.path.join(TEMP_FILES_DIR, f"{pid}.log"), level=DEBUG)`
   before its `logging.exception(...)` calls. Python's
   `logging.basicConfig` is a no-op if the root logger already has
   handlers, so this works by accident — the first call wins per
   child interpreter and everyone gets the same file path. A single
   `_setup_child_logging()` call at the top of `_run_fit_child`
   would make the intent obvious and remove the per-site
   `basicConfig` boilerplate. Also opens the door to a centralized
   error-ID registry (`zunzun/error_ids.py`) so field-debugging
   reports can reference stable IDs instead of free-form messages.

**Why it's worth fixing.** Both are observability/robustness
improvements that pay off most when something goes wrong in
production. The retry-on-read is a small win for users whose fits
get stuck under SQLite-lock contention; the centralized logging
setup is a maintenance win that scales as more child code paths are
added.

**Where to pick up.**

1. **For the read retry**: extract `_save_with_retry(session, ...)`
   (see the existing entry "Factor out session.save() retry helper"
   above) and add a sibling `_load_with_retry(session, key, ...)`
   that mirrors the loop. Update `LoadItemFromSessionStore` to use
   it. Narrow the helper's exception-swallow path
   (`_we_own_status_slot`) to log-only — actual retries happen
   one layer down.
2. **For the logging setup**: add `zunzun/LongRunningProcess/child_logging.py`
   with `setup_child_logging(pid) -> None` that calls `basicConfig`
   once with the standard `temp/{pid}.log` filename. Call it from
   `_run_fit_child` after `django.setup()`. Replace the 17 inline
   `basicConfig` calls with bare `logging.exception(...)`. Bonus:
   add `error_ids.py` with named constants for the major failure
   classes (`OWNERSHIP_READ_FAILED`, `TERMINAL_HTML_WRITE_FAILED`,
   `BROKEN_PROCESS_POOL`, etc.) and reference them in log messages.

**Not in scope of any current branch.** Cross-cutting changes that
shouldn't bundle into the race-condition fix PR. The read-retry
work overlaps the existing "Factor out session.save() retry helper"
entry — both should land together.

## ~~Backfill `FunctionFinderResults.SetInitialStatusDataIntoSessionVariables`~~ RESOLVED 2026-05-29

> **Resolution.** Added `"parallelProcessCount": 0` to the initial-status
> dict in `FunctionFinderResults.SetInitialStatusDataIntoSessionVariables`,
> matching the base contract from
> `StatusMonitoredLongRunningProcessPage.SetInitialStatusDataIntoSessionVariables`.
> The key now appears between `redirectToResultsFileOrURL` and
> `dispatched_at` so the two overrides line up byte-for-byte except for
> the `currentStatus` string. Pytest 133/133 green. Did not take the
> optional `_default_initial_status_dict()` factor-out — only one
> overrider currently exists, so the abstraction wouldn't pay off yet.
>
> Historical notes below, preserved for reference.

**Symptom / exposure.** The base
`SetInitialStatusDataIntoSessionVariables` in
`StatusMonitoredLongRunningProcessPage` writes
`{"currentStatus", "start_time", "time_of_last_status_check",
"redirectToResultsFileOrURL", "parallelProcessCount", "dispatched_at"}`
into the status session. The override in
`FunctionFinderResults.SetInitialStatusDataIntoSessionVariables` was
updated in `fix/pipeline-error-redirects` to stamp `dispatched_at`
(so `_we_own_status_slot()` works on the FFR path) but still omits
`parallelProcessCount`. Minor inconsistency: if a previous run left
a stale `parallelProcessCount` in the session, the FFR child sees
that stale value until something else overwrites it.

**Why it's worth fixing.** Small, mechanical, removes a subtle
inconsistency. Either the base contract is "every override writes
all initial-state keys" or it isn't — the current state is half
each.

**Where to pick up.**

1. Add `"parallelProcessCount": 0` to the
   `SaveDictionaryOfItemsToSessionStore` payload in
   `FunctionFinderResults.SetInitialStatusDataIntoSessionVariables`.
2. Optionally factor the common keys into a base-class helper
   `_default_initial_status_dict()` that both
   `StatusMonitoredLongRunningProcessPage.SetInitial...` and the
   `FunctionFinderResults` override call into; the FFR override
   then overrides only the `currentStatus` string ("Initializing
   Reports and Graphs" vs the base's "Initializing").

**Not in scope of any current branch.** Cosmetic consistency; no
observable bug under current code paths.

## Pre-migration in-flight fits are not resumed across deploy

**Symptom.** When the `feat/lrp-status-table` code is deployed while a user
already has a fit in progress from the *previous* (status-session-blob)
code, that user's browser session has the old `session_key_status` but no
`lrp_status_pk`. The new `StatusView` / `StatusUpdateView` / per-user gate
look up the `LRPStatus` row by `lrp_status_pk`, find nothing, and treat the
still-running fit as absent — so its status page can no longer show progress
or deliver the result. The abandoned child finishes (or is reaped) on its
own; only the *view* of it is lost.

**Hypothesis / scope.** A one-time cutover artifact, not a steady-state bug.
It can only affect fits that were mid-flight at the exact moment of the
deploy that introduces the `LRPStatus` table.

**What we did NOT do, and why.** Codex (PR #21, comment 3328546514)
suggested keeping a `session_key_status` fallback read path until old
sessions expire, or migrating the session pointer on read. We declined: the
whole point of the `2026-05-29-lrp-status-table-design.md` refactor was to
*delete* the status-session apparatus (`_we_own_status_slot`,
`_publish_terminal_error`, `dispatched_at`, `session_key_status`). Re-adding
a parallel blob-read path — permanent code in the hot request path for a
one-time transition — reintroduces exactly the dual-read surface the
refactor removed, and the fallback would itself need test coverage and a
removal date.

**Mitigation (chosen).** Drain in-progress fits before deploying (see
`docs/deployment/README.md`, "Upgrades and redeploys"). Fits are short, so a
brief drain window before the Waitress restart fully avoids the symptom.

**Where to pick up.** If a future deploy genuinely cannot drain (e.g. a
long-running FunctionFinder must survive a restart), the cleanest path is a
one-shot data migration that mints an `LRPStatus` row from any live
`session_key_status` blob and stamps `lrp_status_pk` into that session —
transitional and removable — rather than a permanent dual-read in the views.

## True per-dispatch isolation for ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=True

**Symptom.** With `ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=True` (the dev
default), two fits in one browser session interfere in two ways Codex flagged
on PR #21 (comments 3329374711 and 3329374713):

1. **Shared result blobs (3329374711).** `data` and `functionfinder` are
   per-SESSION SessionStores, not per-dispatch. The supersession guard in
   `RenderOutputHTMLToAFileAndSetStatusRedirect` (skip-when-row-missing) only
   fires when a row was deleted; in concurrent mode the prior row is now
   preserved (commit 92c6075), so an older concurrent child still has a live
   `process_id`, passes the guard, and can overwrite the shared `data` blob
   that `/EvaluateAtAPoint/` reads — yielding stale/mixed follow-up
   evaluations against whichever result `lrp_status_pk` currently points at.

2. **Single status pointer (3329374713).** There is one `lrp_status_pk` per
   browser session. A second concurrent dispatch overwrites it, so the first
   fit's already-open status tab begins polling the newer row; the first row
   stops receiving `StatusUpdateView` heartbeats and, after 300s,
   `CheckIfStillUsed` tears the first (wanted) child down — or its terminal
   redirect is simply never served.

**Scope / why deferred.** Both are inherent to concurrent mode and were out
of scope for the status-table cutover (`2026-05-29-lrp-status-table-design.md`,
which explicitly kept `data`/`functionfinder` as session blobs and the status
pointer as a single session key). The **production-recommended setting is
`ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=False`**, under which the per-user
gate admits only one live fit at a time and neither issue can arise. The
`True` default is a single-user local-dev convenience.

**What we did NOT do, and why.** Did not make `data`/`functionfinder`
per-dispatch or give each status page its own dispatch-scoped id this round —
that is a genuine architecture change (new per-dispatch stores or a
DB-backed data row keyed by dispatch pk, plus a status URL that carries the
dispatch id instead of reading the mutable session pointer), not a localized
fix, and it would expand PR #21 well past its stated scope.

**Where to pick up.** Two coordinated pieces: (a) move the `data`/
`functionfinder` payloads to per-dispatch storage (e.g. keyed by the
`LRPStatus` pk, or folded into the row) so a superseded child cannot clobber
the winner; (b) make the status page address its dispatch's row by id in the
URL (e.g. `/StatusAndResults/<pk>/`) rather than the single
`request.session['lrp_status_pk']`, so concurrent fits each keep a live,
independently-heartbeated status view. With (b), the housekeeping/abandonment
thresholds also need revisiting so a backgrounded-but-wanted concurrent fit
isn't reaped. Until then, document `False` as the supported multi-user
posture.
