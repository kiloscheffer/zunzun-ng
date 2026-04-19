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

## Task 4: Apply load-site casts in `EvaluateAtAPointView`

**Files:**
- Modify: `zunzun/views.py` — two sites: `scipySpline` load at line ~97-98, `solvedCoefficients` load at line ~116.

This task runs whether or not Tasks 2/3 hit outcome B. If they passed (outcome A), the cast is belt-and-braces hardening against future scipy/pyeq3 strictness; if they failed (outcome B), the cast is the fix that makes them pass.

- [ ] **Step 1: Import numpy at the top of `EvaluateAtAPointView`**

Open `zunzun/views.py` and locate `EvaluateAtAPointView`. It already does `import numpy` at module scope (see line 130: `numpy.array([[evaluationForm.cleaned_data['x']], [1.0]])`), so no new import is needed. Skip to Step 2 — this step exists only to make you confirm the import is present.

- [ ] **Step 2: Cast `scipySpline` back to `(ndarray, ndarray, int)` at the load site**

In `zunzun/views.py`, find the `if equation.splineFlag:` block (currently line 97-98):

```python
    if equation.splineFlag:
        equation.scipySpline = LRP.LoadItemFromSessionStore('data', 'scipySpline')
```

Replace the assignment with:

```python
    if equation.splineFlag:
        # scipySpline is stored as [knots, coefs, degree] after
        # _json_native collapses the original (ndarray, ndarray, int) tuple.
        # scipy's BSpline / splev want the original shape.
        raw_spline = LRP.LoadItemFromSessionStore('data', 'scipySpline')
        equation.scipySpline = (
            numpy.array(raw_spline[0]),
            numpy.array(raw_spline[1]),
            int(raw_spline[2]),
        )
```

- [ ] **Step 3: Cast `solvedCoefficients` back to ndarray at the shared load line**

Find the line (currently line 116):

```python
    equation.solvedCoefficients = LRP.LoadItemFromSessionStore('data', 'solvedCoefficients')
```

Replace with:

```python
    # solvedCoefficients is stored as a list after _json_native. pyeq3's
    # CalculateModelPredictions expects an ndarray.
    equation.solvedCoefficients = numpy.array(
        LRP.LoadItemFromSessionStore('data', 'solvedCoefficients')
    )
```

- [ ] **Step 4: Run full smoke to confirm both round-trips pass**

Run:
```bash
UV_LINK_MODE=copy uv run python scripts/smoke_test.py
```
Expected: `SMOKE OK: all scenarios passed`. Both `[evaluate_at_a_point_spline] OK` and `[evaluate_at_a_point_udf] OK` in the output.

- [ ] **Step 5: Run pytest to confirm no regression**

Run:
```bash
UV_LINK_MODE=copy uv run pytest tests/ -v
```
Expected: same pass count as Task 1 Step 3 (no change — pytest doesn't exercise `EvaluateAtAPointView`).

- [ ] **Step 6: Commit**

```bash
git add zunzun/views.py
git commit -m "Cast session-loaded spline + coefficients back to numpy shape

EvaluateAtAPointView was reading scipySpline as [list, list, int] (the
_json_native output) and handing it to scipy's splev, which historically
expected a tuple of ndarrays. Likewise solvedCoefficients was a plain
list where pyeq3 expects an ndarray. Cast back at the load sites so the
shape matches what the downstream consumers expect, independent of
future scipy/pyeq3 strictness."
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
