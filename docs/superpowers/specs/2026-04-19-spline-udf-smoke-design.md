# Spline + UDF smoke coverage — design

**Date:** 2026-04-19
**Branch:** `spline-udf-smoke`
**Worktree:** `C:\Dropbox\git\zunzunsite3-spline-udf\`
**Closes TODO entry:** "Spline + UDF session round-trip not smoke-covered" (introduced during the Django 5.2 migration, 2026-04-18).

## 1. Goal

Add two end-to-end smoke scenarios to `scripts/smoke_test.py` that exercise the round-trip through the session store for the two fit types currently uncovered by smoke:

1. **`FitSpline`** — whose `SaveSpecificDataToSessionStore` writes `scipySpline`, a tuple `(knots_ndarray, coefs_ndarray, degree_int)`, through `_json_native`. `_json_native` converts both ndarrays to Python lists and the enclosing tuple to a Python list, so what lands in the session is `[list_of_floats, list_of_floats, int]`. `EvaluateAtAPointView` loads this verbatim into `equation.scipySpline` and hands it to scipy's `CalculateModelPredictions` downstream.
2. **`FitUserDefinedFunction`** — whose `SaveSpecificDataToSessionStore` writes a string `udfEditor_2D` (the function source) and a numpy-coerced `solvedCoefficients` list. `EvaluateAtAPointView` re-parses the string and loads the coefficients list.

Both round-trips are executed on every production request to `/EvaluateAtAPoint/` but have **zero** smoke coverage. Pytest coverage exists only at the pickle/payload layer (`tests/test_pickle_spike.py`), not at the session-roundtrip layer.

## 2. What we're building

### 2.1 New smoke scenarios

Two scenarios added to `scripts/smoke_test.py` after the existing 10:

| # | name | POST URL | chained |
|---|------|----------|---------|
| 11 | `spline_2D` | `/FitEquation__F__/2/Spline/Spline/` | `evaluate_at_a_point_spline` |
| 12 | `udf_2D` | `/FitEquation__F__/2/UserDefinedFunction/UserDefinedFunction/` | `evaluate_at_a_point_udf` |

Each scenario follows the same shape as the existing `polynomial_quadratic_2D` + `evaluate_at_a_point` pair in `scripts/smoke_test.py:462-485`:
1. POST form fields to the fit URL.
2. Poll `/StatusAndResults/` until final body arrives (no `REDIRECT`/`REFRESH` markers).
3. Assert fit-output structural markers in the final body.
4. POST `x=7.0` to `/EvaluateAtAPoint/`.
5. Assert the response contains `"evaluates to"` (existing `_EVAL_AT_POINT_MARKERS`).

Both reuse `_DATA_2D_POLY` — 10 rows with distinct X values, well above the `splineOrderX + 1 = 4` minimum. No new dataset is needed.

### 2.2 URL dispatch

Neither `/FitSpline/` nor `/FitUserDefinedFunction/` is a real URL pattern. Both spline and UDF fits route through the generic `re_path(r"^FitEquation__F__/([23])/(.+)/(.+)/$", ...)` in `urls.py:11`, and the LRP dispatcher in `views.py:279-291` picks the correct subclass by substring-matching `request.path`:

- `request.path.find('UserDefinedFunction')` → `FitUserDefinedFunction`
- `request.path.find('Spline')` → `FitSpline`
- otherwise → `FitOneEquation`

The canonical URL formats used by the home page are:

- Spline 2D: `/Equation/2/Spline/Spline/`
- UDF 2D: `/Equation/2/UserDefinedFunction/UserDefinedFunction/`

Either `FitEquation__F__/` or `Equation/` URL prefix works — both route through `LongRunningProcessView` per `urls.py:11-12` and are accepted by the dispatcher. The smoke uses the `FitEquation__F__/` prefix for consistency with scenarios 1, 4, and 7.

### 2.3 Form field constants

Two new module-level dicts in `scripts/smoke_test.py`, adjacent to `_POLY_QUAD_FIELDS`:

```python
_SPLINE_2D_FIELDS = {
    # All the shared base fields from _POLY_QUAD_FIELDS, minus fittingTarget
    # (FitSpline.SpecificEquationBoundInterfaceCode sets required=False).
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
    # Spline-specific (FitSpline.SpecificEquationBoundInterfaceCode marks
    # both required=True on bind).
    "splineSmoothness": "1.0",
    "splineOrderX": "3",
}

_UDF_2D_FIELDS = dict(
    _POLY_QUAD_FIELDS,
    # Simplest non-trivial linear UDF — two coefficients that fit the 10-
    # point polynomial dataset cleanly. The round-trip also exercises
    # ParseAndCompileUserFunctionString in EvaluateAtAPointView.
    udfEditor="a + b*X",
)
```

### 2.4 Expected-marker sets

Spline output pages do not render `"Coefficient Covariance Matrix"` — splines have knots and B-spline coefficients, not parameter covariance in the Fisher-information sense. Use a smaller marker set:

```python
_SPLINE_EXPECTED_MARKERS = [
    "Coefficient and Fit Statistics",
    "Minimum:",
    "Maximum:",
    "Coefficients And Text Reports",
]
```

UDF output pages do render covariance (pyeq3's `CalculateCoefficientAndFitStatistics` produces it for `UserDefinedFunction`), so UDF reuses `_POLY_EXPECTED_MARKERS`.

If implementation reveals either set is wrong (e.g., spline also lacks `"Coefficients And Text Reports"`), trim the set during implementation. The decision rule: markers must be stable across pyeq3/numpy/scipy minor versions and present in the response body for a healthy fit.

### 2.5 Scenario placement

Insert after the existing `invalid_form_post` block, before the `if errors:` summary at the end of `run_smoke()`. This keeps the scenario numbering logical and means failures in the new scenarios don't short-circuit the existing suite.

The scenario block follows the pattern from `polynomial_quadratic_2D` at `scripts/smoke_test.py:462-485`:

```python
err = _run_scenario(
    session, base, "spline_2D",
    base + "/FitEquation__F__/2/Spline/Spline/",
    _SPLINE_2D_FIELDS, _SPLINE_EXPECTED_MARKERS,
    timeout_s=600,
)
if err:
    errors.append(err)
else:
    print("[spline_2D] OK")
    r = session.post(base + "/EvaluateAtAPoint/",
                     data=_EVAL_AT_POINT_FIELDS, allow_redirects=True)
    err = _check_markers("evaluate_at_a_point_spline", r.text, _EVAL_AT_POINT_MARKERS)
    if err:
        errors.append(err)
    else:
        print("[evaluate_at_a_point_spline] OK")

# ...identical shape for udf_2D + evaluate_at_a_point_udf.
```

## 3. Fix-in-branch policy for round-trip failures

### 2026-04-20 scope refinement (applied after Task 2 smoke observation)

The original hypothesis below was off by one level of the stack. Task 2's smoke revealed that `FitSpline.SaveSpecificDataToSessionStore` writes the **live** `scipy.interpolate.UnivariateSpline` object into the session dict, not a pre-extracted tck tuple. `_json_native` does not know how to collapse a scipy spline object (it falls through all `isinstance` checks), so Django's `JSONSerializer` crashes on session save with `TypeError: Object of type UnivariateSpline is not JSON serializable` — the spline fit never completes, and the read-side cast the spec originally prescribed is never reached.

The real fix is at the write site: drop the `scipySpline` key from the session dict entirely. It is redundant because `solvedCoefficients` already holds the spline's tck tuple — see `pyeq3/Services/SolverService.py:365-368` for 2D (`scipySpline = scipy.interpolate.UnivariateSpline(...)` then `solvedCoefficients = scipySpline._eval_args`) and line 371-379 for 3D (`scipySpline.tck`). The load site then reconstructs a callable spline from the tck:

- 2D: `scipy.interpolate.BSpline(t, c, k)` — callable with the same `scipySpline(X)` semantics pyeq3 uses at `Models_2D/Spline.py:57`.
- 3D: a small wrapper class exposing `.ev(X, Y)` via `scipy.interpolate.bisplev(X, Y, (tx, ty, c, kx, ky))`, matching `Models_3D/Spline.py:60`'s `self.scipySpline.ev(X, Y)` call shape.

The UDF read-side cast from the original spec is still good — UDF does not have the same write-site problem because its saved values (the function-text string and the `solvedCoefficients` numpy array) both pass through `_json_native` cleanly. The cast is still worth adding as hardening.

### Original hypothesis, preserved

The primary hypothesis in the TODO entry is that spline `Evaluate-at-a-Point` will raise a `TypeError` inside scipy because `scipySpline` was stored as `[list, list, int]` (the `_json_native` output) but scipy's `BSpline`/`splev` path expects a tuple of ndarrays.

If the new smoke fails at the evaluate step, the fix is to cast back at the **load site** in `EvaluateAtAPointView`, not the write site — the `_json_native` contract across all Fit* subclasses is "whatever goes in comes out JSON-native". Each consumer casts to the shape it needs.

**Spline fix, at `zunzun/views.py:98`:**

```python
if equation.splineFlag:
    raw = LRP.LoadItemFromSessionStore('data', 'scipySpline')
    # raw is [list, list, int] after _json_native. scipy.BSpline /
    # splev want tck=(t, c, k) where t, c are ndarrays and k is int.
    import numpy
    equation.scipySpline = (
        numpy.array(raw[0]),
        numpy.array(raw[1]),
        int(raw[2]),
    )
```

**UDF fix, at `zunzun/views.py:116` (`solvedCoefficients`):**

```python
import numpy
equation.solvedCoefficients = numpy.array(
    LRP.LoadItemFromSessionStore('data', 'solvedCoefficients')
)
```

The UDF fix applies to the line that already exists at `views.py:116` — that line is shared across all paths, so the cast could also be added once there rather than inside the UDF branch. Prefer the one-line shared fix.

Both fixes are belt-and-braces: if the smoke passes without them (i.e., scipy/pyeq3 have gotten more permissive over the years and internally coerce the list inputs), the fixes can still be added as explicit-is-better-than-implicit hardening, since the cast is cheap and the TODO entry's concern about "scipy historically strict about array-vs-list types" is a real future-compatibility risk.

**Decision at implementation time:** run the smoke without any fix first. If either Evaluate step fails, add the corresponding fix in the same branch. If both pass, add both fixes anyway as hardening and re-run smoke to prove the hardened code still works.

## 4. What we're NOT doing

- **Not** adding spline or UDF fits to the 3D path. 3D spline is a separate form shape (`splineOrderY` added), 3D UDF is a separate formula constraint (`a + b*X + c*Y`), and the TODO entry only claims risk for the 2D shapes because that's what Phase 3 of the Django upgrade touched. Future work if desired.
- **Not** exercising FunctionFinder → Evaluate round-trip for ranked spline/UDF entries — FunctionFinder doesn't rank either of these families; they're user-initiated fits only.
- **Not** touching `_json_native` itself. The "cast at load site" policy is already how every Fit* subclass works today, and changing that would cascade through every `EvaluateAtAPointView` branch.
- **Not** adding pytest unit tests for spline/UDF session round-trip. The pytest suite doesn't have a real SessionStore running; attempting to test the round-trip there would require stubbing the session backend. The smoke test runs the real Waitress + SQLite session backend, which is the only place this bug can be reproduced faithfully.

## 5. Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| New scenario fails intermittently on SQLite lock contention (session DB shared with parallel spawn children). | Existing smoke has 10 scenarios that all hit the same session DB; the retry loop in `SaveDictionaryOfItemsToSessionStore` handles contention. No mitigation needed beyond matching the existing pattern. |
| UDF formula `a + b*X` produces degenerate coefficients for `_DATA_2D_POLY` (scattered y values). | The formula is linear, the data is noisy but monotonic — pyeq3's `differential_evolution` initial estimate plus the quasi-Newton solve will converge. The smoke doesn't assert specific coefficient values, only that the fit output page renders and Evaluate returns a number. |
| Spline output markers don't match reality. | Trim during implementation; the marker list is a verification heuristic, not a contract. |
| Smoke run-time grows from ~2 min to ~3 min on Windows. | Acceptable. The two new scenarios are among the fastest — linear UDF + 3rd-order spline on 10 points, each under 10 s. |

## 6. Deliverables

1. New scenarios in `scripts/smoke_test.py` (≈ 80 lines added).
2. Possibly 1–4 line fixes in `zunzun/views.py` at the `EvaluateAtAPointView` load sites.
3. `TODO.md` entry marked RESOLVED (strikethrough heading + resolution block matching the pattern used for the two already-resolved entries on 2026-04-19).
4. `CLAUDE.md` line 30 ("40 tests cover...") — no change; pytest count unchanged since this is smoke-only work.
5. Local merge to master; no push to origin per user preference.

## 7. Verification

Smoke must pass end-to-end with `uv run python scripts/smoke_test.py` (prefixed with `UV_LINK_MODE=copy` on Dropbox). Budget: ≤ 5 min on Windows, ≤ 3 min on Linux.

Existing pytest suite (`uv run pytest tests/ -v`) must still pass — no pytest changes in this branch, but run it to confirm no accidental regression.
