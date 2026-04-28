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

## Modernize HTML/CSS in templates (in progress)

**Status:** pass 1 landed in commit `0011366` / merge `39676c6` (2026-04-28).
Pass 2 (HTML5 DOCTYPE + semantic wrappers + non-conforming attribute
removal) is the in-flight work as of the same date. Remaining: layout
table → grid/flexbox conversion (the bigger structural pass) is still
deferred to a future dedicated effort.

**Pass 1 (done — commit `0011366`):**

- Added `modern-normalize` and `simple.css` via `<link>` tags in
  `generic_page_template.html`.
- Removed obsolete elements: `<center>`, `<font>`, `<basefont>`,
  `<style type="text/css">` → `<style>`.
- Removed `border="0"` on images.
- Replaced `<HR WIDTH="X%">` with `<hr style="width:X%">`.
- 27 templates touched, -8 net lines.

**Pass 2 (in this commit):**

- Upgraded HTML 4.01 DOCTYPE → `<!DOCTYPE html>` in the 3 templates
  that declared one.
- Wrapped `generic_page_template.html`'s page-level structure in
  semantic `<header>` / `<main>` / `<footer>` so simple.css's
  body-scoped styles apply correctly (footer auto-centers, content
  gets main padding).
- Removed non-conforming attributes: `cellpadding`, `cellspacing`,
  `valign`, `nowrap` (35 sites across templates).

**Remaining work (future passes):**

**Symptom / exposure (original, partially addressed).**
`templates/zunzun/*.html` originally used deprecated HTML 4.01
elements and attributes throughout. Pass 1 + pass 2 have addressed
the elements and several attribute classes; what remains:

- **Layout tables:** `<table>` used for visual positioning rather
  than tabular data. Most of the home page's menu, the function
  finder interface form layout, etc. are layout tables. simple.css
  styles them as data tables (borders, alternating rows, padding),
  which is visually wrong for layout use.
- **`align="center"` on tables, divs, and cells:** non-conforming
  in HTML5 but functionally important — removing them shifts
  layout left. Replacement requires either a `.layout-table`
  class that resets simple.css's table styling, or full conversion
  to grid/flexbox.
- **`<TABLE BORDER="1">` for visible-bordered data-entry tables:**
  non-conforming but functional. simple.css's table styling
  partially overrides; needs review per-table.
- **Inline `style="display:none"` and `align='center'` on `<div>`s:**
  used by the show/hide JavaScript on the home page. Replacement
  requires touching the JS too, not just templates.
- **Uppercase HTML tag names (`<TABLE>`, `<TR>`, `<TD>`, etc.):**
  cosmetic; HTML5 is case-insensitive. A search-and-replace pass
  would lowercase everything for stylistic consistency. Big diff,
  no functional change.

Pre-pass-1, all the original deprecated patterns were present
(see commit `0011366` for the full list with substitution rules).

**Why it's worth fixing.**

- Aesthetic — the maintainer plans a layout modernization.
- Linter cleanliness — current state generates 100+ deprecation
  warnings in any HTML5 validator.
- Mobile / responsive — table-based layouts don't reflow on
  small screens; CSS grid/flexbox does.
- Future browser compatibility — at some point a major browser
  may drop deprecated elements entirely. Unlikely soon, but the
  longer it's deferred the more code accumulates that depends on
  the old shape.

**Where to pick up.**

1. Pick one template as a pattern-establishing pilot.
   `templates/zunzun/divs/about.html` is the smallest target
   (currently ~20 lines) and was deliberately styled to match
   the rest of the site, so updating it sets the convention.
2. Convert table-based layouts to CSS grid or flexbox.
3. Replace `<FONT>` and `<BASEFONT>` with semantic HTML
   (`<h2>`, `<strong>`, etc.) plus a CSS class for sizing.
4. Move inline `align` / `border` / `cellpadding` / `nowrap`
   attributes to a stylesheet.
5. Replace `<center>` with CSS centering (text or flexbox).
6. Add a single `temp/static_images/zunzun.css` (matching the
   existing static-image-serving convention) for the shared
   rules. Reference it from `generic_page_template.html` so all
   pages pick it up.
7. Run output through an HTML linter (`htmlhint`,
   `vnu.jar`, etc.) and iterate until clean.
8. Visually QA each affected page in a browser before/after.
9. Once the pattern is established, work through the remaining
   templates incrementally — each one is a small focused commit.

**Not in scope of any current branch.** Cosmetic; no behavior
change. Smoke test's substring-marker assertions on
`ZunZunNG`, `Polynomial`, `Thank you`, etc. don't match on
layout HTML, so they're robust to the modernization. The
maintainer plans this as a future dedicated effort.
