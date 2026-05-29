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

## Factor out session.save() retry helper

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

## Auto-coerce numpy values via custom JSONEncoder

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

## Replace pid_trace.py with proper logging

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

## Convert CommonToAllViews to Django middleware

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

## Modernize legacy DOM access in matrix-selector JavaScript

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

## Split the LRP status session blob into per-field rows

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

## Replace eval() with getattr() in LRP session helpers

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

## Test coverage for dispatch-ownership and terminal-error helpers

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

## Robustness improvements in LRP child logging and session reads

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

2. **`logging.basicConfig` is re-called at 17 sites in the LRP
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

## Backfill `FunctionFinderResults.SetInitialStatusDataIntoSessionVariables`

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
