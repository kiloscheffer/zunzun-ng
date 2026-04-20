# Spline + UDF smoke coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two end-to-end smoke scenarios (`spline_2D`, `udf_2D`) — each chained to a follow-up `/EvaluateAtAPoint/` POST — to prove the session round-trip through `_json_native` works for `FitSpline.scipySpline` and `FitUserDefinedFunction.solvedCoefficients`. Apply belt-and-braces casts at the two `EvaluateAtAPointView` load sites so both paths remain robust to future scipy/pyeq3 strictness.

**Architecture:** The smoke test (`scripts/smoke_test.py`) drives a throwaway Waitress against localhost, submits Django form-encoded POSTs, and polls `/StatusAndResults/` until completion. Each new scenario mirrors the existing `polynomial_quadratic_2D` + `evaluate_at_a_point` pair (pattern at `scripts/smoke_test.py:462-485`). Both new scenarios reuse `_DATA_2D_POLY` (10 distinct X points). The spline fit uses form fields `splineSmoothness=1.0`, `splineOrderX=3`; the UDF fit uses `udfEditor="a + b*X"`. Load-site casts live in `zunzun/views.py` at the `EvaluateAtAPointView` branches that consume spline or coefficient data.

**Tech Stack:** Python 3.14, Waitress, Django 6.0, pytest, scipy, pyeq3, numpy, requests (smoke client). No new dependencies.

**Reference:** Design spec at `docs/superpowers/specs/2026-04-19-spline-udf-smoke-design.md`.

**Worktree:** `C:\Dropbox\git\zunzunsite3-spline-udf\` (branch `spline-udf-smoke`, base `master`). All commands below are run from this worktree root.

**Windows / Dropbox constraint:** All `uv` commands must be prefixed with `UV_LINK_MODE=copy` because the repo lives on a Dropbox-synced filesystem that does not support hardlinks. Shell is bash (via Git for Windows); use forward slashes and Unix syntax.

---

## File Structure

**Modified files:**

- `scripts/smoke_test.py` — add spline + UDF constants, add two scenario blocks, extend module docstring.
- `zunzun/views.py` — belt-and-braces casts at `EvaluateAtAPointView`'s spline-load branch (line ~97-98) and at the shared `solvedCoefficients` load line (line ~116).
- `TODO.md` — strike through the "Spline + UDF session round-trip not smoke-covered" heading and add a resolution block, matching the pattern used for the other two resolved entries.

**Created files:** None.

**Deleted files:** None.

---

## Task 1: Baseline — sync deps, migrate session DB, confirm current smoke + pytest green

**Files:** None modified. Environmental sanity check only.

- [ ] **Step 1: Sync dependencies in the worktree**

Run:
```bash
cd /c/Dropbox/git/zunzunsite3-spline-udf
UV_LINK_MODE=copy uv sync
```
Expected: `uv` prints `Resolved N packages` and `Installed N packages` (or `Audited N packages` if already cached from the primary worktree), no errors.

- [ ] **Step 2: Create the session DB (fresh worktree has none)**

Run:
```bash
UV_LINK_MODE=copy uv run python manage.py migrate
```
Expected: creates `session_db/db.sqlite3`, prints `Applying sessions.0001_initial... OK`.

- [ ] **Step 3: Run baseline pytest**

Run:
```bash
UV_LINK_MODE=copy uv run pytest tests/ -v
```
Expected: `40 passed` (±1–2 — the count is informational, not a hard gate). All must be green.

- [ ] **Step 4: Run baseline smoke**

Run:
```bash
UV_LINK_MODE=copy uv run python scripts/smoke_test.py
```
Expected: `SMOKE OK: all scenarios passed`. 10 scenarios pass. No commit — this is a pre-flight check.

---

## Task 2: Add the `spline_2D` + `evaluate_at_a_point_spline` scenario

**Files:**
- Modify: `scripts/smoke_test.py` — add `_SPLINE_2D_FIELDS`, `_SPLINE_EXPECTED_MARKERS`, and the scenario block.

- [ ] **Step 1: Add the form-field constant**

Insert the following block into `scripts/smoke_test.py` immediately after the `_POLY_QUAD_FIELDS` dict (currently ends around line 89 before the `_FF_2D_FIELDS` comment):

```python
# Spline 2D form fields. Derived from _POLY_QUAD_FIELDS but without
# fittingTarget (FitSpline.SpecificEquationBoundInterfaceCode marks it
# required=False on bind), plus splineSmoothness and splineOrderX which
# FitSpline forces required=True. splineOrderX=3 needs at least 4 distinct
# X values, and _DATA_2D_POLY has 10.
_SPLINE_2D_FIELDS = {
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
    "textDataEditor": _DATA_2D_POLY,
    "splineSmoothness": "1.0",
    "splineOrderX": "3",
}

# Spline output pages do not render "Coefficient Covariance Matrix" —
# splines have knots and B-spline coefficients, not parameter covariance
# in the Fisher-information sense. Marker set is pruned accordingly.
_SPLINE_EXPECTED_MARKERS = [
    "Coefficient and Fit Statistics",
    "Minimum:",
    "Maximum:",
    "Coefficients And Text Reports",
]
```

- [ ] **Step 2: Add the scenario block**

In the `run_smoke` function, insert the following block immediately before the final `if errors:` summary (currently at `scripts/smoke_test.py:609`):

```python
        # spline_2D + round-trip through EvaluateAtAPointView. The
        # round-trip is the real target — FitSpline stores scipySpline as a
        # tuple of ndarrays which _json_native converts to [list, list, int]
        # before session write. EvaluateAtAPointView at views.py:98 loads
        # this verbatim and scipy's splev/BSpline path consumes it.
        err = _run_scenario(
            session,
            base,
            "spline_2D",
            base + "/FitEquation__F__/2/Spline/Spline/",
            _SPLINE_2D_FIELDS,
            _SPLINE_EXPECTED_MARKERS,
            timeout_s=600,
        )
        if err:
            errors.append(err)
        else:
            print("[spline_2D] OK")
            r = session.post(
                base + "/EvaluateAtAPoint/",
                data=_EVAL_AT_POINT_FIELDS,
                allow_redirects=True,
            )
            err = _check_markers(
                "evaluate_at_a_point_spline", r.text, _EVAL_AT_POINT_MARKERS
            )
            if err:
                errors.append(err)
            else:
                print("[evaluate_at_a_point_spline] OK")
```

- [ ] **Step 3: Update the module-docstring scenario list**

In the module-level docstring of `scripts/smoke_test.py` (currently lines 6-22), append an entry after item 10 so the listing stays current. Replace:

```
10. **invalid_form_post** — malformed data → error template.
```

with:

```
10. **invalid_form_post** — malformed data → error template.
11. **spline_2D** — 2D cubic spline fit with smoothness=1.0, chained into
    an `/EvaluateAtAPoint/` POST to verify the `_json_native`-mangled
    `scipySpline` round-trips through the session.
```

- [ ] **Step 4: Run smoke to observe spline behavior**

Run:
```bash
UV_LINK_MODE=copy uv run python scripts/smoke_test.py
```
Expected outcome is one of:
- **A:** `[spline_2D] OK` and `[evaluate_at_a_point_spline] OK` — round-trip works without a cast fix. Proceed.
- **B:** `[spline_2D] OK` but `[evaluate_at_a_point_spline]` missing `"evaluates to"` — the TypeError case the TODO warned about. The body in `temp/_smoke_last_body_evaluate_at_a_point_spline.html` will contain `"Exception in evaluation, please check the data. Exception text:"` followed by the scipy TypeError. Record the finding but DO NOT fix yet — the cast lands in Task 4.
- **C:** `[spline_2D]` missing a marker — marker list is wrong, trim to whichever markers actually appear in `temp/_smoke_last_body_spline_2D.html` and re-run.

Note which outcome you hit; it determines whether Task 4 is mandatory (B) or belt-and-braces (A).

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "Add spline_2D smoke scenario + Evaluate round-trip

Exercises FitSpline.SaveSpecificDataToSessionStore's scipySpline write
and EvaluateAtAPointView's load site. Spline output markers differ from
polynomial output (no covariance matrix for B-spline fits), so uses a
pruned marker set."
```

---

## Task 3: Add the `udf_2D` + `evaluate_at_a_point_udf` scenario

**Files:**
- Modify: `scripts/smoke_test.py` — add `_UDF_2D_FIELDS` and the scenario block.

- [ ] **Step 1: Add the form-field constant**

Insert into `scripts/smoke_test.py` immediately after the `_SPLINE_EXPECTED_MARKERS` block from Task 2:

```python
# UDF 2D form fields. Same base as _POLY_QUAD_FIELDS (UDF uses
# fittingTarget, unlike spline) plus the udfEditor text. "a + b*X" is the
# simplest non-trivial linear UDF — two coefficients, guaranteed to fit
# the 10-point polynomial dataset, and exercises the session
# userDefinedFunctionText round-trip + ParseAndCompileUserFunctionString.
_UDF_2D_FIELDS = dict(
    _POLY_QUAD_FIELDS,
    udfEditor="a + b*X",
)
```

- [ ] **Step 2: Add the scenario block**

In `run_smoke`, insert immediately after the spline block added in Task 2 (and still before the `if errors:` summary):

```python
        # udf_2D + round-trip through EvaluateAtAPointView. Exercises
        # FitUserDefinedFunction's solvedCoefficients write (list after
        # _json_native) and EvaluateAtAPointView's load site.
        err = _run_scenario(
            session,
            base,
            "udf_2D",
            base + "/FitEquation__F__/2/UserDefinedFunction/UserDefinedFunction/",
            _UDF_2D_FIELDS,
            _POLY_EXPECTED_MARKERS,
            timeout_s=600,
        )
        if err:
            errors.append(err)
        else:
            print("[udf_2D] OK")
            r = session.post(
                base + "/EvaluateAtAPoint/",
                data=_EVAL_AT_POINT_FIELDS,
                allow_redirects=True,
            )
            err = _check_markers(
                "evaluate_at_a_point_udf", r.text, _EVAL_AT_POINT_MARKERS
            )
            if err:
                errors.append(err)
            else:
                print("[evaluate_at_a_point_udf] OK")
```

- [ ] **Step 3: Update the module-docstring scenario list**

Replace the item-11 block added in Task 2 with:

```
11. **spline_2D** — 2D cubic spline fit with smoothness=1.0, chained into
    an `/EvaluateAtAPoint/` POST to verify the `_json_native`-mangled
    `scipySpline` round-trips through the session.
12. **udf_2D** — 2D User Defined Function fit with formula `a + b*X`,
    chained into an `/EvaluateAtAPoint/` POST to verify
    `solvedCoefficients` round-trips through the session.
```

- [ ] **Step 4: Run smoke to observe UDF behavior**

Run:
```bash
UV_LINK_MODE=copy uv run python scripts/smoke_test.py
```
Expected outcome is one of:
- **A:** `[udf_2D] OK` and `[evaluate_at_a_point_udf] OK` — round-trip works. Proceed.
- **B:** `[udf_2D] OK` but `[evaluate_at_a_point_udf]` missing `"evaluates to"` — the body in `temp/_smoke_last_body_evaluate_at_a_point_udf.html` will contain the TypeError. Record. Cast lands in Task 4.
- **C:** `[udf_2D]` missing a marker — trim the marker list and re-run.

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "Add udf_2D smoke scenario + Evaluate round-trip

Exercises FitUserDefinedFunction's solvedCoefficients session write
(numpy array → list via _json_native) and EvaluateAtAPointView's load
site. Reuses _POLY_EXPECTED_MARKERS since UDF output includes the full
covariance matrix from pyeq3's CalculateCoefficientAndFitStatistics."
```

---

## Task 4: Fix spline session round-trip — drop live object at write, reconstruct at load

**Scope refinement (2026-04-20).** Task 2's smoke exposed that the write side is broken, not the read side as originally predicted. `FitSpline.SaveSpecificDataToSessionStore` passes the live `scipy.interpolate.UnivariateSpline` object through `_json_native`, which does not know how to collapse it, so Django's `JSONSerializer` raises `TypeError: Object of type UnivariateSpline is not JSON serializable` and the fit never completes. The real fix is to drop the `scipySpline` key from the session write (it is redundant with `solvedCoefficients`, which already is the spline's tck tuple per `pyeq3/Services/SolverService.py:368, 379`), and reconstruct a `scipy.interpolate.BSpline` at the load site. See the spec's §3 scope-refinement note.

**Files:**
- Modify: `zunzun/LongRunningProcess/FitSpline.py` — remove `scipySpline` from the session-store dict in `SaveSpecificDataToSessionStore`.
- Modify: `zunzun/views.py` — rewrite the `splineFlag` load branch in `EvaluateAtAPointView` to reconstruct the spline from `solvedCoefficients` (the tck). Add a `numpy.array` cast on the shared `solvedCoefficients` line for UDF and other paths.

- [ ] **Step 1: Drop the scipySpline key at the write site**

Open `zunzun/LongRunningProcess/FitSpline.py`. Find the `SaveSpecificDataToSessionStore` method (currently lines 22-30):

```python
    def SaveSpecificDataToSessionStore(self):
        # scipySpline is a tuple of numpy arrays; _json_native converts
        # the arrays to lists. The EvaluateAtAPointView will need to
        # reconstruct any spline-typed input from these raw sequences.
        self.SaveDictionaryOfItemsToSessionStore('data', _json_native({'dimensionality':self.dimensionality,
                                                          'equationName':self.inEquationName,
                                                          'equationFamilyName':self.inEquationFamilyName,
                                                          'scipySpline':self.dataObject.equation.scipySpline,
                                                          'solvedCoefficients':self.dataObject.equation.solvedCoefficients}))
```

Replace the method body with:

```python
    def SaveSpecificDataToSessionStore(self):
        # The live scipy.interpolate.UnivariateSpline / SmoothBivariateSpline
        # object is not JSON-serializable; storing it here crashes the
        # session save. It is redundant anyway — solvedCoefficients holds
        # the spline's tck tuple (see pyeq3/Services/SolverService.py:
        # line 368 for 2D UnivariateSpline._eval_args, line 379 for 3D
        # SmoothBivariateSpline.tck). The load site in EvaluateAtAPointView
        # reconstructs the callable from that tck.
        self.SaveDictionaryOfItemsToSessionStore('data', _json_native({'dimensionality':self.dimensionality,
                                                          'equationName':self.inEquationName,
                                                          'equationFamilyName':self.inEquationFamilyName,
                                                          'solvedCoefficients':self.dataObject.equation.solvedCoefficients}))
```

The only change is removing the `'scipySpline': ...` line. Everything else is preserved.

- [ ] **Step 2: Confirm numpy and scipy.interpolate are importable in views.py**

Open `zunzun/views.py`. `import numpy` is already present at module scope (used at line 130 among others). `scipy.interpolate` is **not** currently imported in views.py but is transitively imported via pyeq3; adding an explicit `import scipy.interpolate` at the module top is clearer. If you see an existing `import scipy` line, upgrade it to `import scipy.interpolate`. Otherwise add a new line near the other stdlib/scipy imports.

- [ ] **Step 3: Rewrite the splineFlag branch to reconstruct from tck**

Find the `if equation.splineFlag:` block in `EvaluateAtAPointView` (currently lines 97-98):

```python
    if equation.splineFlag:
        equation.scipySpline = LRP.LoadItemFromSessionStore('data', 'scipySpline')
```

Replace with:

```python
    if equation.splineFlag:
        # scipySpline is a live scipy spline object (UnivariateSpline in 2D,
        # SmoothBivariateSpline in 3D) and is not saved to the session — see
        # FitSpline.SaveSpecificDataToSessionStore. solvedCoefficients IS
        # the tck tuple, which we reconstruct into a callable spline here.
        # pyeq3's Models_2D.Spline.CalculateModelPredictions calls
        # self.scipySpline(X); a BSpline instance is callable with matching
        # semantics. For 3D, wrap bisplev in an .ev(X, Y) helper to match
        # Models_3D.Spline.CalculateModelPredictions' call shape.
        tck = LRP.LoadItemFromSessionStore('data', 'solvedCoefficients')
        if LRP.dimensionality == 2:
            t = numpy.array(tck[0])
            c = numpy.array(tck[1])
            k = int(tck[2])
            equation.scipySpline = scipy.interpolate.BSpline(t, c, k)
        else:
            tx = numpy.array(tck[0])
            ty = numpy.array(tck[1])
            c = numpy.array(tck[2])
            kx = int(tck[3])
            ky = int(tck[4])
            class _BivariateSplineFromTck:
                def ev(self, X, Y):
                    return scipy.interpolate.bisplev(X, Y, (tx, ty, c, kx, ky))
            equation.scipySpline = _BivariateSplineFromTck()
```

- [ ] **Step 4: Cast `solvedCoefficients` to ndarray at the shared load line — with a spline exception**

Find the line (currently line 116 pre-edit, shifted a few lines by Step 3):

```python
    equation.solvedCoefficients = LRP.LoadItemFromSessionStore('data', 'solvedCoefficients')
```

Replace with:

```python
    # solvedCoefficients is stored as a list after _json_native. pyeq3's
    # CalculateModelPredictions expects an ndarray for regular equations.
    # For splines, solvedCoefficients IS the tck tuple (already consumed
    # above to reconstruct equation.scipySpline), and pyeq3's
    # Models_2D/3D.Spline.CalculateModelPredictions ignores inCoeffs —
    # so leave it as-is for the spline case.
    raw_coeffs = LRP.LoadItemFromSessionStore('data', 'solvedCoefficients')
    if equation.splineFlag:
        equation.solvedCoefficients = raw_coeffs
    else:
        equation.solvedCoefficients = numpy.array(raw_coeffs)
```

- [ ] **Step 5: Run full smoke to confirm both round-trips pass**

```bash
UV_LINK_MODE=copy uv run python scripts/smoke_test.py
```
Budget 8 min (480000ms) timeout. Expected: `SMOKE OK: all scenarios passed`. Both `[evaluate_at_a_point_spline] OK` and `[evaluate_at_a_point_udf] OK` in the output. All 12 scenarios pass.

If `[evaluate_at_a_point_spline]` still fails after this, dump `temp/_smoke_last_body_evaluate_at_a_point_spline.html` and report — the BSpline reconstruction may need a different shape than anticipated.

- [ ] **Step 6: Run pytest to confirm no regression**

```bash
UV_LINK_MODE=copy uv run pytest tests/ -v
```
Expected: same pass count as Task 1 Step 3 (the growing suite — whichever number was observed in baseline, that number here too).

- [ ] **Step 7: Commit**

```bash
git add zunzun/LongRunningProcess/FitSpline.py zunzun/views.py
git commit -m "Fix spline session round-trip: drop live object, reconstruct at load

FitSpline.SaveSpecificDataToSessionStore was storing the live
scipy.interpolate.UnivariateSpline / SmoothBivariateSpline object
through _json_native, which does not collapse it — Django's
JSONSerializer then raises TypeError on session save and the fit never
completes. The key is redundant: solvedCoefficients already holds the
spline's tck tuple (see pyeq3/Services/SolverService.py:368, 379).
Drop the scipySpline key entirely at the write site.

EvaluateAtAPointView now reconstructs a callable spline from the tck at
load time — scipy.interpolate.BSpline for 2D, a tiny bisplev-based
wrapper for 3D. Also adds a numpy.array cast for non-spline
solvedCoefficients so pyeq3's CalculateModelPredictions receives the
ndarray shape it expects."
```

---

## Task 5: Close the TODO entry

**Files:**
- Modify: `TODO.md` — strike through the "Spline + UDF session round-trip not smoke-covered" heading (currently line 104) and insert a resolution block at the top of the section.

- [ ] **Step 1: Update the heading and insert the resolution block**

In `TODO.md`, find the line:

```markdown
## Spline + UDF session round-trip not smoke-covered
```

Replace it with the two lines:

```markdown
## ~~Spline + UDF session round-trip not smoke-covered~~ RESOLVED 2026-04-19

> **Resolution.** Two smoke scenarios added to `scripts/smoke_test.py`:
> - `spline_2D` — POSTs a 2D cubic spline fit, chains an
>   `/EvaluateAtAPoint/` POST, asserts `"evaluates to"` is in the
>   response. Exercises the `scipySpline` `_json_native` round-trip.
> - `udf_2D` — POSTs a 2D User Defined Function fit (`a + b*X`), chains
>   an `/EvaluateAtAPoint/` POST, asserts the same marker. Exercises
>   the `solvedCoefficients` + `userDefinedFunctionText` round-trip.
>
> `EvaluateAtAPointView` at `zunzun/views.py` now casts both session-
> loaded values back to their numpy-native shapes (tuple-of-ndarrays for
> spline, ndarray for coefficients) so downstream scipy/pyeq3 consumers
> receive the shapes they were designed for, independent of the
> `_json_native` collapse at the write site.
>
> The smoke suite is now at 12 scenarios; all pass.
>
> Historical notes below, preserved for reference.
```

(Everything below the original heading — the "Symptom / exposure", "When we hit it", "Hypothesis", "Where to pick up", "Not in scope" blocks — stays in place as historical notes.)

- [ ] **Step 2: Commit**

```bash
git add TODO.md
git commit -m "Close spline + UDF round-trip TODO as RESOLVED

Both scenarios added to smoke in the preceding commits, and the load-
site casts in EvaluateAtAPointView provide belt-and-braces safety
against future scipy/pyeq3 strictness. Historical notes preserved."
```

---

## Task 6: Final verification + CLAUDE.md scenario count

**Files:**
- Modify: `CLAUDE.md` — update the "8 scenarios" / "10 scenarios" reference if stale (depends on current state).

- [ ] **Step 1: Check whether CLAUDE.md mentions a specific scenario count**

Run:
```bash
grep -nE '[0-9]+ scenarios?|scenario [0-9]' CLAUDE.md
```
Expected: zero or more hits. Each hit must now reference 12 scenarios, not 10 or 8.

- [ ] **Step 2: If Step 1 found stale counts, update them**

For each stale reference, use the Edit tool to replace the old count with `12`. If Step 1 found no hits, skip.

- [ ] **Step 3: Final full smoke**

Run:
```bash
UV_LINK_MODE=copy uv run python scripts/smoke_test.py
```
Expected: `SMOKE OK: all scenarios passed`, `[spline_2D]`, `[evaluate_at_a_point_spline]`, `[udf_2D]`, `[evaluate_at_a_point_udf]` all print `OK`.

- [ ] **Step 4: Final full pytest**

Run:
```bash
UV_LINK_MODE=copy uv run pytest tests/ -v
```
Expected: same pass count as Task 1. No regressions.

- [ ] **Step 5: If CLAUDE.md was touched in Step 2, commit**

```bash
git add CLAUDE.md
git commit -m "Update CLAUDE.md smoke scenario count

Reflects the two new scenarios added in the spline + UDF round-trip
branch. No other documentation drift found."
```

(If CLAUDE.md had no stale counts, this step is a no-op — commit skipped.)

- [ ] **Step 6: Report summary**

Print a terminal-only summary for the controller:

```
DONE. Commits on branch spline-udf-smoke:
 1. b858f6a  design spec
 2. <sha>    spline_2D scenario
 3. <sha>    udf_2D scenario
 4. <sha>    EvaluateAtAPointView load-site casts
 5. <sha>    TODO.md resolution
 6. <sha>    CLAUDE.md update (if applicable)

Smoke: 12/12 passing. pytest: 40/40 passing (or local baseline).
Ready for controller to merge to master.
```

---

## Task 7: Controller-owned: local merge to master

**Files:** None — this task runs in the PRIMARY worktree, not `zunzunsite3-spline-udf`, and is executed by the controller directly per the user's standing preference ("no push to origin, local merge only").

- [ ] **Step 1: Switch to the primary worktree**

```bash
cd /c/Dropbox/git/zunzunsite3
git status
```
Expected: `On branch master`, clean tree.

- [ ] **Step 2: Merge the feature branch**

```bash
git merge --no-ff spline-udf-smoke -m "Merge spline + UDF session round-trip smoke coverage"
```
Expected: merge commit created with all 5–6 commits from the feature branch brought in; no conflicts (branch was based on master's current HEAD).

- [ ] **Step 3: Remove the worktree and delete the branch**

```bash
git worktree remove ../zunzunsite3-spline-udf
git branch -d spline-udf-smoke
```
Expected: worktree directory removed, branch deleted (not force-deleted — the merge into master makes `-d` safe).

- [ ] **Step 4: Verify final state**

```bash
git worktree list
git log --oneline master -8
```
Expected: only the primary worktree listed; recent log shows the merge commit at the top followed by the feature-branch commits.
