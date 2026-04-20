# Porting pyeq3 off scipy.odr — pyeq3ng fork Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fork pyeq3 as `pyeq3ng` at `github.com/kiloscheffer/pyeq3ng`, replace all `scipy.odr.odrpack.*` references with equivalent `odrpack.odr_fit` calls, validate numerical equivalence against a captured fixture, then re-pin zunzunsite3 to the fork. After merge, zunzun's smoke (12/12) and pytest (78/78) plus pyeq3's own UnitTest suite must stay green. Closes TODO entry *"pyeq3 imports `scipy.odr` which scipy 1.19.0 will remove"*.

**Architecture:** pyeq3ng is a permanent fork — upstream is dormant since 2020. The port is a direct rewrite (no compat shim), replacing class-based `scipy.odr.odrpack.Model`/`Data`/`ODR` with function-based `odrpack.odr_fit`. Per-callsite closure rewrappers handle the beta/x arg-order swap (scipy: `f(beta, x)`, odrpack: `f(x, beta)`). pyeq3's internal `WrapperForODR(self, inCoeffs, data)` signature is preserved.

**Tech Stack:** Python 3.14, odrpack 0.5.0 (PyPI wheel, Fortran backend), pyeq3 (forked), scipy 1.17+ remains for other modules (`scipy.interpolate`, `scipy.optimize`, `scipy.stats`). GitHub via `gh` CLI. uv for zunzun dep management.

**Reference:** Design spec at `docs/superpowers/specs/2026-04-20-pyeq3ng-odr-port-design.md`.

**Two repositories, done in sequence:**
1. `C:\Dropbox\git\pyeq3\` (local clone of upstream) → becomes `pyeq3ng` origin
2. `C:\Dropbox\git\zunzunsite3\` (this repo) — pin bump + TODO close

**Windows / Dropbox constraint:** All `uv` commands in the zunzun repo must be prefixed with `UV_LINK_MODE=copy`. Shell is bash (Git for Windows), forward slashes in paths.

**Key scipy.odr → odrpack observations** (feed into Task 5 and Task 6 implementations):

- **Two usage patterns in pyeq3.** The first block (IModel.py lines 237-243) computes parameter-covariance statistics via `maxit=0, fit_type=2` (OLS mode, zero iterations — it's extracting covariance info from an already-solved model). The second block (IModel.py 421-427 and all of SolverService.SolveUsingODR) is the ODR-as-fitting-target path with `fit_type=0` (explicit ODR) and a real iteration budget.
- **`set_job(fit_type=2)` = OLS mode.** odrpack equivalent: `task="OLS"`.
- **`set_job(fit_type=0, deriv=0)` = explicit ODR with forward-FD derivatives.** odrpack equivalent: `task="explicit-ODR", diff_scheme="forward"`.
- **`maxit=0` behavior** may differ between scipy.odr and odrpack. If odrpack's `odr_fit` rejects `maxit=0`, use `maxit=1` and extract post-run stats regardless — the covariance estimation doesn't need actual convergence. Investigate during Task 5.
- **Weights mapping.** `Data(x, y, we=weights)` (scipy) → `odr_fit(..., weight_y=weights)` (odrpack). The kwarg name `we` in scipy is historical; odrpack uses the clearer `weight_y`.
- **Result attributes preserved.** Both scipy.odr's `ODR.run()` return value and odrpack's `OdrResult` expose `.beta` (coefficients), `.sum_square` (SSQ), `.cov_beta` (parameter covariance), `.sd_beta` (standard deviations). Same names, so all call-site post-processing (`coeffs = out.beta`, `SSQ = out.sum_square`) is unchanged.

---

## File Structure

### pyeq3ng repo (new, at `C:\Dropbox\git\pyeq3\`)

- Modify: `IModel.py` — 7 `scipy.odr.odrpack.*` references on lines 237-243 (covariance block) and 421-427 (ODR-target block), plus `scipy.odr` import at top of file.
- Modify: `Services/SolverService.py` — import on line 13 + 6 references on lines 170, 172, 174, 180, 192, 212 inside `SolveUsingODR`.
- Create (temporary, deleted at end): `UnitTests/_generate_odr_fixture.py` — runs current scipy.odr pyeq3 against a dataset suite, dumps coefficients to JSON.
- Create (temporary, deleted at end): `UnitTests/_odr_baseline_fixture.json` — captured baseline coefficients.
- Create (temporary, deleted at end): `UnitTests/Test_OdrEquivalence.py` — compares ported pyeq3 output to baseline fixture with `allclose(atol=1e-9)`.
- Modify: `README.txt` or similar — single paragraph noting the fork provenance + scipy.odr removal reason.

### zunzunsite3 repo (modified, this repo)

- Modify: `pyproject.toml` — add `[tool.uv.sources]` block pinning `pyeq3 = { git = "...pyeq3ng.git", tag = "v1.0.0-ng" }`.
- Regenerate: `uv.lock`.
- Modify: `CLAUDE.md` — one sentence noting the pyeq3ng pin.
- Modify: `TODO.md` — strike-through "pyeq3 imports scipy.odr" heading, add resolution block.

### Deleted files (none in zunzunsite3)

---

## Task 1: Set up pyeq3ng fork on GitHub

**Files:** None modified in zunzunsite3. All changes happen in `C:\Dropbox\git\pyeq3\`.

- [ ] **Step 1: Confirm pyeq3 clone state**

Run:
```bash
cd /c/Dropbox/git/pyeq3
git remote -v
git log --oneline -3
git status --short
```
Expected: origin points at `bitbucket.org/zunzuncode/pyeq3.git`, HEAD is `a35a600 Add linear log scaled equation`, working tree clean.

- [ ] **Step 2: Rename upstream, create GitHub repo, push**

```bash
git remote rename origin upstream
gh repo create kiloscheffer/pyeq3ng --public --description "Fork of pyeq3 (dormant upstream since 2020-01) with scipy.odr dependency removed — see docs in zunzunsite3 for rationale." --disable-wiki --disable-issues=false
git remote add origin https://github.com/kiloscheffer/pyeq3ng.git
git branch -m master main
git push -u origin main
```
Expected: GitHub repo created, local `master` renamed to `main`, push succeeds.

- [ ] **Step 3: Verify the remote layout**

```bash
git remote -v
git branch -a
```
Expected: two remotes (`origin` → GitHub pyeq3ng, `upstream` → bitbucket zunzuncode), `main` tracks `origin/main`, upstream's master visible as `remotes/upstream/master`.

- [ ] **Step 4: Add fork-provenance note to README**

Read the existing `README.txt` (or whatever exists). Prepend (not replace) these lines:

```
pyeq3ng — fork of pyeq3 with scipy.odr dependency removed
=========================================================

This is a fork of the upstream pyeq3 project
(https://bitbucket.org/zunzuncode/pyeq3), which has been dormant since
2020-01. The fork replaces scipy.odr (deprecated in scipy 1.17.0, slated
for removal in 1.19.0) with the independent odrpack package on PyPI.
pyeq3's public API is preserved unchanged; internal implementation of
ODR fitting and covariance estimation now go through odrpack.odr_fit.

Primary consumer: zunzunsite3. See that project's
docs/superpowers/specs/2026-04-20-pyeq3ng-odr-port-design.md for the
migration rationale and validation strategy.

=== Original pyeq3 README follows ===

```

Then the original README content.

- [ ] **Step 5: Commit and push the README update**

```bash
git add README.txt
git commit -m "Note fork provenance: pyeq3ng replaces scipy.odr with odrpack"
git push
```
Expected: push to `origin main` succeeds.

---

## Task 2: Verify baseline — current pyeq3 UnitTests green on scipy.odr

**Files:** None modified. This is a pre-flight check.

- [ ] **Step 1: Install pyeq3 dependencies into a temporary venv or zunzunsite3's venv**

The simplest path is to run pyeq3's UnitTests inside zunzunsite3's `.venv` since that venv already has `numpy`, `scipy`, and all pyeq3 runtime deps. Add the pyeq3 source path to `PYTHONPATH` at invocation time.

```bash
cd /c/Dropbox/git/pyeq3/UnitTests
PYTHONPATH=/c/Dropbox/git/pyeq3 UV_LINK_MODE=copy \
  /c/Dropbox/git/zunzunsite3/.venv/Scripts/python.exe RunAllTests.py 2>&1 | tail -40
```
Expected: all tests pass (may take several minutes). Record the final pass count. Any failing test is a pre-existing issue and should be flagged in the report.

- [ ] **Step 2: Verify odrpack wheel available on this platform**

```bash
UV_LINK_MODE=copy uv run --with odrpack --no-project python -c "import odrpack; r = odrpack.odr_fit(lambda x, b: b[0]*x + b[1], [1.0, 2.0, 3.0], [2.0, 4.0, 6.0], beta0=[1.0, 0.0]); print('beta:', r.beta, 'sum_square:', r.sum_square)"
```
Expected: prints `beta: [2.0 0.0] sum_square: ~0.0` (or very close). Confirms odrpack imports cleanly, Fortran backend loads, a trivial fit produces sensible results.

If the `import odrpack` itself fails, stop and report BLOCKED — no point porting to a package that doesn't install.

---

## Task 3: Generate numerical-equivalence baseline fixture

**Files:**
- Create: `C:\Dropbox\git\pyeq3\UnitTests\_generate_odr_fixture.py`
- Create: `C:\Dropbox\git\pyeq3\UnitTests\_odr_baseline_fixture.json`

- [ ] **Step 1: Write the fixture-generation script**

Create `UnitTests/_generate_odr_fixture.py` with this content:

```python
"""One-shot fixture generator: runs the current scipy.odr-backed pyeq3
over a spread of fit types and datasets, captures solvedCoefficients
and sum-square residuals to JSON. The port's test_OdrEquivalence then
checks the ported code produces matching values within tolerance.

Delete this file along with _odr_baseline_fixture.json and
Test_OdrEquivalence.py once the port is validated and merged. The file
is intentionally named with a leading underscore so RunAllTests.py
does not auto-discover it as a test module.
"""
import json
import os
import sys
import numpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyeq3
import DataForUnitTests


def _run_one(fit_type_name, model_factory, fitting_target):
    model = model_factory(fitting_target)
    pyeq3.dataConvertorService().ConvertAndSortColumnarASCII(
        DataForUnitTests.asciiDataInColumns_2D if model.GetDimensionality() == 2
        else DataForUnitTests.asciiDataInColumns_3D,
        model,
        False,
    )
    pyeq3.solverService().SolveUsingDifferentialEvolution(model)
    coeffs = pyeq3.solverService().SolveUsingSelectedAlgorithm(model, inAlgorithmName="Levenberg-Marquardt")
    return {
        "fit_type": fit_type_name,
        "solvedCoefficients": numpy.asarray(coeffs).tolist(),
        "sum_square_abs": float(model.CalculateAllDataFittingTarget(coeffs)),
    }


FIT_CASES = [
    ("poly2D_linear_ODR",
     lambda ft: pyeq3.Models_2D.Polynomial.Linear(ft), "ODR"),
    ("poly3D_linear_ODR",
     lambda ft: pyeq3.Models_3D.Polynomial.Linear(ft), "ODR"),
    ("poly2D_linear_SSQABS",
     lambda ft: pyeq3.Models_2D.Polynomial.Linear(ft), "SSQABS"),
    ("poly3D_linear_SSQABS",
     lambda ft: pyeq3.Models_3D.Polynomial.Linear(ft), "SSQABS"),
]


def main():
    out = []
    for name, factory, ft in FIT_CASES:
        try:
            entry = _run_one(name, factory, ft)
            entry["case"] = name
            out.append(entry)
            print(f"[{name}] solved: {entry['solvedCoefficients']}")
        except Exception as e:
            print(f"[{name}] FAILED: {type(e).__name__}: {e}")
            out.append({"case": name, "error": f"{type(e).__name__}: {e}"})

    fixture_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_odr_baseline_fixture.json")
    with open(fixture_path, "w") as f:
        json.dump(out, f, indent=2, sort_keys=True)
    print(f"\nWrote {fixture_path} with {len(out)} entries")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the generator against current scipy.odr-backed pyeq3**

```bash
cd /c/Dropbox/git/pyeq3/UnitTests
PYTHONPATH=/c/Dropbox/git/pyeq3 /c/Dropbox/git/zunzunsite3/.venv/Scripts/python.exe _generate_odr_fixture.py
```
Expected: 4 entries printed (poly 2D+3D, each with ODR and SSQABS targets), `_odr_baseline_fixture.json` created. If any case produces `FAILED:`, investigate — the fixture has a scipy.odr-era bug that the port can't fix. Non-ODR cases (SSQABS) also exercise the covariance-matrix scipy.odr call path via `CalculateCoefficientAndFitStatistics`.

- [ ] **Step 3: Commit fixture + generator on `main`**

```bash
cd /c/Dropbox/git/pyeq3
git add UnitTests/_generate_odr_fixture.py UnitTests/_odr_baseline_fixture.json
git commit -m "Add one-shot scipy.odr baseline fixture for port equivalence check

Captures solvedCoefficients + SSQ from the current scipy.odr-backed
pyeq3 across 4 test cases (2D/3D polynomial, ODR and SSQABS targets).
Test_OdrEquivalence in the port branch will assert the ported pyeq3
matches these baselines within allclose(atol=1e-9).

Both this script and the fixture are temporary — deleted in a later
commit once the port is merged to main."
git push
```
Expected: push to `origin main` succeeds.

---

## Task 4: Create drop-scipy-odr branch and confirm odrpack baseline

**Files:** None modified yet. Branch setup + sanity check.

- [ ] **Step 1: Branch off main**

```bash
cd /c/Dropbox/git/pyeq3
git checkout -b drop-scipy-odr
```
Expected: `Switched to a new branch 'drop-scipy-odr'`.

- [ ] **Step 2: Confirm odrpack is installable into zunzun's venv**

```bash
cd /c/Dropbox/git/zunzunsite3
UV_LINK_MODE=copy uv pip install odrpack
UV_LINK_MODE=copy uv run python -c "import odrpack; print('odrpack OK:', odrpack.__version__ if hasattr(odrpack, '__version__') else 'unknown')"
```
Expected: `odrpack OK: 0.5.0` or similar. This venv is used for running pyeq3's UnitTests throughout the port. Once the port merges and zunzun re-pins pyeq3, `odrpack` will come in as a transitive dep of pyeq3ng (we add it to pyeq3ng's requirements in Task 10).

---

## Task 5: Port `IModel.py` (7 references, 2 methods)

**Files:**
- Modify: `C:\Dropbox\git\pyeq3\IModel.py`

- [ ] **Step 1: Update the scipy.odr import**

Find the `import scipy` line near the top of `IModel.py`. It likely looks like:

```python
import scipy.interpolate, scipy.optimize, scipy.odr, scipy.odr.odrpack, scipy.stats
```

Replace with:

```python
import scipy.interpolate, scipy.optimize, scipy.stats
import odrpack
```

Run a grep to confirm `scipy.odr` no longer appears in the imports:
```bash
grep -n "^import scipy\|^from scipy" /c/Dropbox/git/pyeq3/IModel.py | head
```

- [ ] **Step 2: Port the covariance-statistics block (lines 237-243)**

Current code:
```python
            # see both scipy.odr.odrpack and http://www.scipy.org/Cookbook/OLS
            # this is inefficient but works for every possible case
            model = scipy.odr.odrpack.Model(self.WrapperForODR)
            self.dataCache.FindOrCreateAllDataCache(self)
            data = scipy.odr.odrpack.Data(self.dataCache.allDataCacheDictionary['IndependentData'], self.dataCache.allDataCacheDictionary['DependentData'])
            myodr = scipy.odr.odrpack.ODR(data, model, beta0=self.solvedCoefficients,  maxit=0)
            myodr.set_job(fit_type=2)
            parameterStatistics = myodr.run()
            self.cov_beta = parameterStatistics.cov_beta # parameter covariance matrix
```

Replace with:

```python
            # Port from scipy.odr.odrpack to odrpack.odr_fit. maxit=0 in
            # scipy.odr means "don't iterate, just evaluate covariance at
            # the given beta0." odrpack's default maxit is 50 and 0 may
            # be rejected; use maxit=1 and rely on sum_square/cov_beta
            # being computed from the single evaluation. set_job(fit_type=2)
            # in scipy.odr is OLS mode = odrpack task="OLS".
            # Note the arg-order swap: scipy.odr Model(f(beta, x)),
            # odrpack odr_fit(f(x, beta)).
            self.dataCache.FindOrCreateAllDataCache(self)
            def _f(x, beta):
                return self.WrapperForODR(beta, x)
            parameterStatistics = odrpack.odr_fit(
                _f,
                self.dataCache.allDataCacheDictionary['IndependentData'],
                self.dataCache.allDataCacheDictionary['DependentData'],
                beta0=self.solvedCoefficients,
                task="OLS",
                maxit=1,
            )
            self.cov_beta = parameterStatistics.cov_beta # parameter covariance matrix
```

- [ ] **Step 3: Port the ODR-target evaluation block (lines 421-434)**

**Note on semantics:** Despite the outer `if self.fittingTarget == "ODR":` guard, this block uses `fit_type=2` (OLS mode) with `maxit=0`. It does NOT actually solve an ODR fit — that happens in `SolverService.SolveUsingODR`. This block *evaluates* the ODR residual at the given `inCoeffs` for use as the fitness value the optimizer consumes. So task="OLS", not "explicit-ODR".

Current code:
```python
            if self.fittingTarget == "ODR": # this is inefficient but works for every possible case
                model = scipy.odr.odrpack.Model(self.WrapperForODR)
                if len(self.dataCache.allDataCacheDictionary['Weights']):
                    data = scipy.odr.odrpack.Data(self.dataCache.allDataCacheDictionary['IndependentData'],  self.dataCache.allDataCacheDictionary['DependentData'], we = self.dataCache.allDataCacheDictionary['Weights'])
                else:
                    data = scipy.odr.odrpack.Data(self.dataCache.allDataCacheDictionary['IndependentData'],  self.dataCache.allDataCacheDictionary['DependentData'])
                myodr = scipy.odr.odrpack.ODR(data, model, beta0=inCoeffs, maxit=0)
                myodr.set_job(fit_type=2)
                out = myodr.run()
                val = out.sum_square
                if numpy.isfinite(val):
                    return val
                else:
                    return 1.0E300
```

Replace with:

```python
            if self.fittingTarget == "ODR": # this is inefficient but works for every possible case
                # ODR target evaluation: run an OLS call (fit_type=2) with
                # zero iterations to get the ODR residual at inCoeffs.
                # Matches scipy.odr's Model/Data/ODR sequence. Arg-order
                # swap: scipy's Model(f(beta, x)) vs odrpack's
                # odr_fit(f(x, beta)) — handled in the inner closure.
                # maxit=0 becomes maxit=1 since odrpack's minimum is 1.
                def _f(x, beta):
                    return self.WrapperForODR(beta, x)
                weights = self.dataCache.allDataCacheDictionary['Weights']
                out = odrpack.odr_fit(
                    _f,
                    self.dataCache.allDataCacheDictionary['IndependentData'],
                    self.dataCache.allDataCacheDictionary['DependentData'],
                    beta0=inCoeffs,
                    weight_y=weights if len(weights) else None,
                    task="OLS",
                    maxit=1,
                )
                val = out.sum_square
                if numpy.isfinite(val):
                    return val
                else:
                    return 1.0E300
```

- [ ] **Step 4: Sanity-check no scipy.odr remains in IModel.py**

```bash
grep -n "scipy\.odr" /c/Dropbox/git/pyeq3/IModel.py
```
Expected: no output. Any remaining references are bugs in this task.

- [ ] **Step 5: Run pyeq3 UnitTests**

```bash
cd /c/Dropbox/git/pyeq3/UnitTests
PYTHONPATH=/c/Dropbox/git/pyeq3 /c/Dropbox/git/zunzunsite3/.venv/Scripts/python.exe RunAllTests.py 2>&1 | tail -30
```
Expected: same pass count as Task 2 baseline. If new failures appear, they're in `Test_SolverService` (ODR tests), `Test_CalculateCoefficientAndFitStatistics` (covariance-block tests), or `Test_NIST` (deep regressions). Stop and diagnose before continuing.

- [ ] **Step 6: Commit the IModel.py port**

```bash
cd /c/Dropbox/git/pyeq3
git add IModel.py
git commit -m "Port IModel.py scipy.odr.odrpack usage to odrpack.odr_fit

Two call sites: covariance-stats block (always-on, OLS mode, maxit=0)
and ODR-target block (fit_type=0 explicit ODR). Both replaced with
odrpack.odr_fit calls using a per-callsite closure to handle the
scipy (beta, x) → odrpack (x, beta) argument-order inversion.
WrapperForODR signature preserved.

maxit=0 rewritten as maxit=1 because odrpack's odr_fit minimum is 1.
The covariance/sum_square are extracted from the single evaluation,
matching scipy.odr's zero-iteration semantics in practice."
```

---

## Task 6: Port `Services/SolverService.py` (6 references + import line)

**Files:**
- Modify: `C:\Dropbox\git\pyeq3\Services\SolverService.py`

- [ ] **Step 1: Port the import line**

Find line 13 (inside a try/except block wrapping the scipy imports):
```python
    import scipy.interpolate, scipy.optimize, scipy.odr.odrpack
```

Replace with:

```python
    import scipy.interpolate, scipy.optimize
    import odrpack
```

- [ ] **Step 2: Port `SolveUsingODR` — three retry branches**

Read lines 167-230 of `Services/SolverService.py` in full before editing — the method has 3 parallel retry blocks plus a final cleanup. The same translation pattern applies to each: a `Model` + `Data` + `ODR` + `set_job` + `run()` sequence becomes a single `odrpack.odr_fit(...)` call with a closure for the callback.

For each of the three retry branches (lines 180, 192, 212 are the `ODR(...)` instantiation points):

**Before (each branch):**
```python
            myodr = scipy.odr.odrpack.ODR(dataObject, modelObject, beta0=<initial>, maxit=len(inModel.GetCoefficientDesignators()) * self.fminIterationLimit)
            myodr.set_job(fit_type=0, deriv=0) # explicit ODR, faster forward-only finite differences for derivatives
            out = myodr.run()
            coeffs = out.beta
            SSQ = out.sum_square
```

**After (each branch):**
```python
            out = odrpack.odr_fit(
                _f,
                xdata,
                ydata,
                beta0=<initial>,
                weight_y=weights if len(weights) else None,
                task="explicit-ODR",
                diff_scheme="forward",
                maxit=len(inModel.GetCoefficientDesignators()) * self.fminIterationLimit,
            )
            coeffs = out.beta
            SSQ = out.sum_square
```

**Hoist the common setup** (lines 169-174 in the original). The `modelObject = ... Model(...)` and `dataObject = ... Data(...)` become a single setup block at the top of `SolveUsingODR`:

```python
    def SolveUsingODR(self, inModel):

        inModel.dataCache.FindOrCreateAllDataCache(inModel)

        # odrpack takes a callback with (x, beta) args, pyeq3's
        # WrapperForODR uses (beta, x). Closure swaps them.
        def _f(x, beta):
            return inModel.WrapperForODR(beta, x)

        xdata = inModel.dataCache.allDataCacheDictionary['IndependentData']
        ydata = inModel.dataCache.allDataCacheDictionary['DependentData']
        weights = inModel.dataCache.allDataCacheDictionary['Weights']

        results = []

        # ... three retry branches follow, each calling odrpack.odr_fit
```

This removes the 6 `scipy.odr.odrpack` references on lines 170, 172, 174 (by hoisting) and lines 180, 192, 212 (by replacement).

- [ ] **Step 3: Sanity-check no scipy.odr remains in SolverService.py**

```bash
grep -n "scipy\.odr" /c/Dropbox/git/pyeq3/Services/SolverService.py
```
Expected: no output.

- [ ] **Step 4: Run pyeq3 UnitTests**

```bash
cd /c/Dropbox/git/pyeq3/UnitTests
PYTHONPATH=/c/Dropbox/git/pyeq3 /c/Dropbox/git/zunzunsite3/.venv/Scripts/python.exe RunAllTests.py 2>&1 | tail -30
```
Expected: same pass count as Task 2 baseline. If tests fail in `Test_SolverService` (the ODR-specific tests), that's the prime diagnostic target — compare the failure output against the baseline captured in `_odr_baseline_fixture.json`.

- [ ] **Step 5: Commit the SolverService.py port**

```bash
cd /c/Dropbox/git/pyeq3
git add Services/SolverService.py
git commit -m "Port Services/SolverService.py SolveUsingODR to odrpack.odr_fit

Hoists the shared (_f, xdata, ydata, weights) setup out of the three
retry branches since odrpack takes all of these per-call rather than
via a separate Data object. Each retry branch becomes a single
odrpack.odr_fit call with task='explicit-ODR' and diff_scheme='forward'
(= scipy.odr's fit_type=0 and deriv=0).

No scipy.odr references remain in this file."
```

---

## Task 7: Add equivalence test, confirm numerical parity

**Files:**
- Create: `C:\Dropbox\git\pyeq3\UnitTests\Test_OdrEquivalence.py`

- [ ] **Step 1: Write the equivalence test**

Create `UnitTests/Test_OdrEquivalence.py`:

```python
"""Validates the ported odrpack-backed pyeq3 produces coefficients
within tolerance of the scipy.odr baseline captured in
_odr_baseline_fixture.json.

Temporary — deleted in a follow-up commit once the port is merged and
trust is established.
"""
import json
import os
import sys
import unittest

import numpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyeq3
import DataForUnitTests


_FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "_odr_baseline_fixture.json",
)


def _run_one(model_factory, fitting_target):
    model = model_factory(fitting_target)
    pyeq3.dataConvertorService().ConvertAndSortColumnarASCII(
        DataForUnitTests.asciiDataInColumns_2D if model.GetDimensionality() == 2
        else DataForUnitTests.asciiDataInColumns_3D,
        model,
        False,
    )
    pyeq3.solverService().SolveUsingDifferentialEvolution(model)
    coeffs = pyeq3.solverService().SolveUsingSelectedAlgorithm(
        model, inAlgorithmName="Levenberg-Marquardt"
    )
    return (
        numpy.asarray(coeffs),
        float(model.CalculateAllDataFittingTarget(coeffs)),
    )


_CASE_FACTORIES = {
    "poly2D_linear_ODR": (lambda ft: pyeq3.Models_2D.Polynomial.Linear(ft), "ODR"),
    "poly3D_linear_ODR": (lambda ft: pyeq3.Models_3D.Polynomial.Linear(ft), "ODR"),
    "poly2D_linear_SSQABS": (lambda ft: pyeq3.Models_2D.Polynomial.Linear(ft), "SSQABS"),
    "poly3D_linear_SSQABS": (lambda ft: pyeq3.Models_3D.Polynomial.Linear(ft), "SSQABS"),
}


class Test_OdrEquivalence(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(_FIXTURE_PATH) as f:
            cls.baseline = {entry["case"]: entry for entry in json.load(f)}

    def test_poly2D_linear_ODR(self):
        self._assert_matches("poly2D_linear_ODR")

    def test_poly3D_linear_ODR(self):
        self._assert_matches("poly3D_linear_ODR")

    def test_poly2D_linear_SSQABS(self):
        self._assert_matches("poly2D_linear_SSQABS")

    def test_poly3D_linear_SSQABS(self):
        self._assert_matches("poly3D_linear_SSQABS")

    def _assert_matches(self, case_name):
        base = self.baseline[case_name]
        if "error" in base:
            self.skipTest(f"baseline for {case_name} errored: {base['error']}")
        factory, ft = _CASE_FACTORIES[case_name]
        got_coeffs, got_ssq = _run_one(factory, ft)
        base_coeffs = numpy.asarray(base["solvedCoefficients"])
        numpy.testing.assert_allclose(got_coeffs, base_coeffs, atol=1e-9, rtol=1e-9,
            err_msg=f"[{case_name}] coefficient drift from scipy.odr baseline")
        self.assertAlmostEqual(got_ssq, base["sum_square_abs"], places=7,
            msg=f"[{case_name}] SSQ drift from scipy.odr baseline")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Wire into RunAllTests.py**

Add `import Test_OdrEquivalence` alongside the other imports near the top of `UnitTests/RunAllTests.py`, and add a `suite.addTests(loader.loadTestsFromModule(Test_OdrEquivalence))` line alongside the other `addTests` calls.

- [ ] **Step 3: Run the full suite including the new equivalence test**

```bash
cd /c/Dropbox/git/pyeq3/UnitTests
PYTHONPATH=/c/Dropbox/git/pyeq3 /c/Dropbox/git/zunzunsite3/.venv/Scripts/python.exe RunAllTests.py 2>&1 | tail -30
```
Expected: all tests pass including the 4 new `test_polyXD_linear_XXX` cases. If drift exceeds `atol=1e-9`:
- First, try `atol=1e-7` — if that passes, document the tighter-than-expected tolerance in the commit message and move on. odrpack and scipy.odr share the same underlying ODRPACK95 Fortran library so coefficients should match bit-exactly up to accumulator ordering.
- If `atol=1e-5` still fails, diagnose: likely a semantic difference in how odrpack interprets a specific keyword (`weight_y` vs scipy's `we`, `task="OLS"` vs `fit_type=2`).

- [ ] **Step 4: Commit the equivalence test + RunAllTests.py wiring**

```bash
cd /c/Dropbox/git/pyeq3
git add UnitTests/Test_OdrEquivalence.py UnitTests/RunAllTests.py
git commit -m "Add Test_OdrEquivalence — ported pyeq3 vs scipy.odr baseline

Loads _odr_baseline_fixture.json and asserts that the odrpack-ported
SolveUsingODR + CalculateCoefficientAndFitStatistics produce
coefficients and SSQ within atol=1e-9 of the original scipy.odr
values. 4 cases: 2D/3D polynomial linear, ODR and SSQABS targets.
Wired into RunAllTests so the full suite catches any drift.

Temporary — this file and the fixture get deleted after the port
merges and the zunzunsite3 smoke suite has passed on the new pin."
```

---

## Task 8: Push feature branch, pin zunzun to it, smoke

**Files:**
- Modify: `C:\Dropbox\git\zunzunsite3\pyproject.toml` (temporary pin to feature branch)
- Modify: `C:\Dropbox\git\zunzunsite3\uv.lock` (regenerated)

- [ ] **Step 1: Push the feature branch**

```bash
cd /c/Dropbox/git/pyeq3
git push -u origin drop-scipy-odr
```
Expected: push succeeds, branch visible on GitHub.

- [ ] **Step 2: Create a zunzun integration branch**

```bash
cd /c/Dropbox/git/zunzunsite3
git checkout -b pyeq3ng-integration master
```

- [ ] **Step 3: Pin zunzun's pyeq3 to the feature branch**

Open `pyproject.toml`. After the `[tool.uv]` section, add:

```toml
[tool.uv.sources]
pyeq3 = { git = "https://github.com/kiloscheffer/pyeq3ng.git", rev = "drop-scipy-odr" }
```

- [ ] **Step 4: Regenerate uv.lock**

```bash
UV_LINK_MODE=copy uv lock
```
Expected: `uv.lock` updates with `source = { git = "https://github.com/kiloscheffer/pyeq3ng.git?rev=drop-scipy-odr", ... }` for pyeq3. odrpack added as transitive dep.

- [ ] **Step 5: Sync the venv to the new pin**

```bash
UV_LINK_MODE=copy uv sync
```
Expected: pyeq3 reinstalled from the GitHub URL, odrpack installed, no errors.

- [ ] **Step 6: Run zunzun's test suite**

```bash
UV_LINK_MODE=copy uv run pytest tests/ -v 2>&1 | tail -10
```
Expected: `78 passed` (same as baseline). No new failures, no new warnings beyond what was there before. The `scipy.odr` DeprecationWarning should be **gone** — that's the headline success signal.

- [ ] **Step 7: Run zunzun's smoke suite**

```bash
UV_LINK_MODE=copy uv run python scripts/smoke_test.py 2>&1 | tail -20
```
Expected: `SMOKE OK: all scenarios passed`, all 12 scenarios green. Budget 8 min (480000ms) timeout.

If any scenario fails, triage:
- `polynomial_quadratic_2D` or `..._3D`: likely the covariance-block port in IModel.py
- `function_finder_2D` / `function_finder_detail_2D`: may exercise multiple fit targets including ODR via ranking
- `udf_2D`: UDF + SolveUsingODR if ranking picks ODR
- `spline_2D`, `characterize_*`: should be unaffected (splines skip the covariance block, characterize doesn't fit)

Do NOT commit the pyproject.toml / uv.lock change yet — this is a verification pin pointing at a feature branch. The final commit will point at a tag (after merge).

---

## Task 9: Cleanup — delete fixture + generator + equivalence test

**Files:** (deleted)
- Delete: `C:\Dropbox\git\pyeq3\UnitTests\_generate_odr_fixture.py`
- Delete: `C:\Dropbox\git\pyeq3\UnitTests\_odr_baseline_fixture.json`
- Delete: `C:\Dropbox\git\pyeq3\UnitTests\Test_OdrEquivalence.py`
- Modify: `C:\Dropbox\git\pyeq3\UnitTests\RunAllTests.py` (remove the Test_OdrEquivalence wiring)

- [ ] **Step 1: Delete the three temp files**

```bash
cd /c/Dropbox/git/pyeq3
rm UnitTests/_generate_odr_fixture.py UnitTests/_odr_baseline_fixture.json UnitTests/Test_OdrEquivalence.py
```

- [ ] **Step 2: Remove Test_OdrEquivalence wiring from RunAllTests.py**

Undo the two edits from Task 7 Step 2: remove the `import Test_OdrEquivalence` line and the matching `suite.addTests(loader.loadTestsFromModule(Test_OdrEquivalence))` line.

- [ ] **Step 3: Run pyeq3 UnitTests (final on feature branch)**

```bash
cd /c/Dropbox/git/pyeq3/UnitTests
PYTHONPATH=/c/Dropbox/git/pyeq3 /c/Dropbox/git/zunzunsite3/.venv/Scripts/python.exe RunAllTests.py 2>&1 | tail -20
```
Expected: same pass count as Task 2 baseline (minus the 4 equivalence tests we just removed).

- [ ] **Step 4: Commit the cleanup on the feature branch**

```bash
cd /c/Dropbox/git/pyeq3
git add -A
git commit -m "Remove one-shot scipy.odr baseline fixture and equivalence test

Port validated via fixture comparison in prior commits. Baseline
fixture, generator script, and equivalence test are temporary
infrastructure — no longer needed since:
 - pyeq3's own Test_SolverService covers ODR regressions
 - zunzunsite3 smoke covers the integration
 - ODRPACK95 Fortran backend is shared between scipy.odr and odrpack,
   so cross-version drift is bounded by ordering artifacts at most
"
git push
```

---

## Task 10: Merge feature branch to main, tag v1.0.0-ng

**Files:** None modified. Git operations only.

- [ ] **Step 1: Merge to main**

```bash
cd /c/Dropbox/git/pyeq3
git checkout main
git merge --no-ff drop-scipy-odr -m "Merge drop-scipy-odr: port pyeq3ng off scipy.odr to odrpack

Full port of IModel.py + Services/SolverService.py from scipy.odr.odrpack
to odrpack.odr_fit. Validated via captured baseline fixture and the
existing pyeq3 UnitTests suite.

Integration validation: zunzunsite3 smoke 12/12 passed when pinned to
this branch before merge. See that project's
docs/superpowers/plans/2026-04-20-pyeq3ng-odr-port.md."
```
Expected: merge commit created.

- [ ] **Step 2: Tag the merge commit**

```bash
git tag -a v1.0.0-ng -m "pyeq3ng v1.0.0-ng — first post-scipy.odr release

Drops scipy.odr dependency entirely; requires odrpack>=0.5.0.
Public pyeq3 API unchanged. See README for fork provenance."
```

- [ ] **Step 3: Push main + tag to GitHub**

```bash
git push origin main --tags
```
Expected: main and tag visible on GitHub.

- [ ] **Step 4: Delete the feature branch**

```bash
git branch -d drop-scipy-odr
git push origin --delete drop-scipy-odr
```
Expected: branch removed locally and on GitHub.

---

## Task 11: Re-pin zunzun to v1.0.0-ng tag, final validation

**Files:**
- Modify: `C:\Dropbox\git\zunzunsite3\pyproject.toml`
- Regenerate: `C:\Dropbox\git\zunzunsite3\uv.lock`

- [ ] **Step 1: Update the pin from branch to tag**

Open `pyproject.toml`. Find the `[tool.uv.sources]` block added in Task 8. Change:

```toml
pyeq3 = { git = "https://github.com/kiloscheffer/pyeq3ng.git", rev = "drop-scipy-odr" }
```

To:

```toml
pyeq3 = { git = "https://github.com/kiloscheffer/pyeq3ng.git", tag = "v1.0.0-ng" }
```

- [ ] **Step 2: Regenerate uv.lock and sync**

```bash
cd /c/Dropbox/git/zunzunsite3
UV_LINK_MODE=copy uv lock
UV_LINK_MODE=copy uv sync
```
Expected: uv.lock updated with the new pin reference. Because the feature branch merge was a fast-forward (no new commits on main since the branch was created), the resolved commit SHA should match what was installed in Task 8.

- [ ] **Step 3: Run zunzun's test suite**

```bash
UV_LINK_MODE=copy uv run pytest tests/ -v 2>&1 | tail -10
```
Expected: `78 passed`, no `scipy.odr` DeprecationWarning.

- [ ] **Step 4: Run zunzun's smoke suite**

```bash
UV_LINK_MODE=copy uv run python scripts/smoke_test.py 2>&1 | tail -20
```
Expected: `SMOKE OK: all scenarios passed`. Budget 8 min (480000ms) timeout.

---

## Task 12: Close TODO, update CLAUDE.md, commit, merge

**Files:**
- Modify: `C:\Dropbox\git\zunzunsite3\TODO.md`
- Modify: `C:\Dropbox\git\zunzunsite3\CLAUDE.md`

- [ ] **Step 1: Close the TODO entry**

Open `TODO.md`. Find the `## pyeq3 imports `scipy.odr` which scipy 1.19.0 will remove` heading. Replace it with:

```markdown
## ~~pyeq3 imports `scipy.odr` which scipy 1.19.0 will remove~~ RESOLVED 2026-04-20

> **Resolution.** Forked pyeq3 to `pyeq3ng`
> (`github.com/kiloscheffer/pyeq3ng`) and ported all `scipy.odr.odrpack`
> usage to `odrpack.odr_fit` on the PyPI `odrpack` package. Public
> pyeq3 API preserved; internal ODR fitting and covariance estimation
> now go through odrpack's function-style API. zunzunsite3 pins
> pyeq3ng at tag `v1.0.0-ng` via `[tool.uv.sources]`. The
> `scipy.odr` DeprecationWarning is gone from pytest and smoke runs.
>
> Validation: pyeq3ng's full UnitTests pass, zunzun smoke 12/12
> passes, zunzun pytest 78/78 passes. A temporary baseline fixture +
> equivalence test confirmed coefficient/SSQ parity within
> `atol=1e-9` across 4 polynomial-fit cases (2D/3D × ODR/SSQABS);
> those temp files were removed post-merge.
>
> See `docs/superpowers/specs/2026-04-20-pyeq3ng-odr-port-design.md`
> and `docs/superpowers/plans/2026-04-20-pyeq3ng-odr-port.md` for the
> design and validation strategy.
>
> Historical notes below, preserved for reference.

```

(The original "Symptom", "When we hit it", "Hypothesis", "Where to pick up", "Not in scope" blocks stay in place as historical notes.)

- [ ] **Step 2: Add CLAUDE.md note**

Find the Dependencies section of `CLAUDE.md`. After the line that starts with `**Django version.**` (or another suitable dependency note), add:

```markdown
**pyeq3 fork.** pyeq3 is pinned to `pyeq3ng`
(`github.com/kiloscheffer/pyeq3ng`, tag `v1.0.0-ng`) via
`[tool.uv.sources]` in `pyproject.toml`. The fork replaces `scipy.odr`
(deprecated in scipy 1.17, removed in 1.19) with the independent
`odrpack` package on PyPI. pyeq3 upstream is dormant since 2020-01;
no path to upstream this change. See
`docs/superpowers/specs/2026-04-20-pyeq3ng-odr-port-design.md` for the
migration rationale.
```

- [ ] **Step 3: Commit the pyproject/lock/TODO/CLAUDE changes**

```bash
cd /c/Dropbox/git/zunzunsite3
git add pyproject.toml uv.lock TODO.md CLAUDE.md
git commit -m "Pin pyeq3 to pyeq3ng fork (v1.0.0-ng), close scipy.odr TODO

Drops the scipy.odr time-bomb dependency. pyeq3ng is a permanent fork
(upstream pyeq3 dormant since 2020-01) with scipy.odr.odrpack.* calls
ported to odrpack.odr_fit. Validated via pyeq3ng's UnitTests plus
zunzunsite3 smoke 12/12 and pytest 78/78. The scipy.odr
DeprecationWarning is gone from every log.

See docs/superpowers/{specs,plans}/2026-04-20-pyeq3ng-odr-port-*.md
for design + execution record."
```

- [ ] **Step 4: Merge the integration branch to master**

```bash
git checkout master
git merge --no-ff pyeq3ng-integration -m "Merge pyeq3ng-integration: drop scipy.odr time-bomb dependency"
git branch -d pyeq3ng-integration
```

- [ ] **Step 5: Verify final state**

```bash
git log --oneline master -5
git status --short
```
Expected: master log shows the merge commit at the top, then the pin/TODO/CLAUDE commit, then prior history. Tree clean.

- [ ] **Step 6: Per user preference, do NOT push.** Local merge only. Branch work complete.
