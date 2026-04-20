# Porting pyeq3 off scipy.odr — pyeq3ng fork design

**Date:** 2026-04-20
**Closes TODO entry:** "pyeq3 imports scipy.odr which scipy 1.19.0 will remove" (pre-existing, pinned in `TODO.md`).
**Strategy chosen over:** pin `scipy<1.19` (short-term), adapter/shim layer (medium), or vendoring `scipy.odr` into pyeq3 (also medium).

## 1. Goal

Replace pyeq3's dependency on `scipy.odr` (deprecated in scipy 1.17.0, removed in 1.19.0) with the independent `odrpack` package on PyPI. The port is a direct rewrite (no compatibility shim), hosted in a permanent fork of pyeq3 named **pyeq3ng**, pinned from zunzunsite3 via `[tool.uv.sources]`. After merge, zunzun's smoke suite (12/12) and pyeq3's own UnitTest suite must stay green.

## 2. Why a direct port, not a shim

- **Shim buys very little** — the scipy.odr API (`Model`/`Data`/`ODR` classes, stateful `run()` call) is fundamentally different shape from odrpack's function-style `odr_fit`. Bridging them means emulating scipy's class semantics on top of odrpack, then maintaining that emulation against both sides of the compatibility. The single compat module becomes its own surface.
- **Upstream pyeq3 is dormant** — last commit 2020-01-19, single author. No realistic pathway to submit a compat-layer PR that gets merged. The fork is permanent. Given that, the code should reflect its actual dependency (odrpack), not carry a bridge to a library it no longer uses.
- **Direct port is mechanical across a bounded surface** — 14 lines to modify across 2 files: `IModel.py` has 7 `scipy.odr.odrpack.*` references in 2 methods, `Services/SolverService.py` has 6 such references across 3 retry branches of `SolveUsingODR` plus the module import. Logical "ODR setup blocks" (each a Model + Data + ODR + run sequence) count to ~5. Once the translation pattern is established the remaining sites follow the same template.

## 3. Fork architecture

**Name:** `pyeq3ng` (user's chosen convention; matches a future `ZunZunNG` rename of zunzunsite3 itself).

**Host:** GitHub, under user's personal account (e.g., `github.com/<user>/pyeq3ng`). Standard uv/pip git+URL pinning works across Windows/Linux/macOS without custom path configuration.

**Seed:** the local clone at `C:\Dropbox\git\pyeq3`. Rename origin to `upstream`, add a new `origin` pointing at GitHub, push `main`. The existing `master` branch from upstream stays as the snapshot point; all our work happens on `main` (more conventional name for a fork's default branch).

**Zunzun pin:**

```toml
# pyproject.toml
[tool.uv.sources]
pyeq3 = { git = "https://github.com/<user>/pyeq3ng.git", tag = "v1.0.0-ng" }
```

Using a named tag (not a branch) makes the pin reproducible. uv records the commit SHA in `uv.lock` regardless, but the tag gives humans a stable reference.

## 4. Core port — API mapping

### scipy.odr → odrpack translation

Every callsite follows this template:

**Before (scipy.odr):**

```python
modelObject = scipy.odr.odrpack.Model(inModel.WrapperForODR)
# WrapperForODR signature: (inCoeffs, data) — beta first
dataObject = scipy.odr.odrpack.Data(xdata, ydata)                # or (...Data, Weights) when weighted
myodr = scipy.odr.odrpack.ODR(dataObject, modelObject,
                              beta0=initial_coeffs,
                              maxit=iteration_limit)
myodr.set_job(fit_type=0, deriv=0)                               # explicit ODR, forward-FD derivatives
out = myodr.run()
coeffs = out.beta
SSQ = out.sum_square
```

**After (odrpack):**

```python
# WrapperForODR rewrapped inline to match odrpack's (x, beta) order;
# pyeq3's native WrapperForODR keeps its (beta, x) signature unchanged.
def _f(x, beta):
    return inModel.WrapperForODR(beta, x)

out = odrpack.odr_fit(
    _f,
    xdata,
    ydata,
    beta0=initial_coeffs,
    weight_y=weights if len(weights) else None,                  # odrpack handles weights on y; x weights is a separate kw
    task="explicit-ODR",                                          # = scipy.odr fit_type=0
    diff_scheme="forward",                                        # = scipy.odr deriv=0
    maxit=iteration_limit,
)
coeffs = out.beta
SSQ = out.sum_square
```

Key semantic differences to verify during port:

| scipy.odr | odrpack | Notes |
|-----------|---------|-------|
| `Model(f_beta_x)` callback | `f_x_beta` inline wrapper | Arg order swap is the one mandatory adapter per callsite. |
| `Data(x, y)` / `Data(x, y, w)` | `odr_fit(..., weight_y=w)` | Weights move from constructor to `odr_fit` keyword. |
| `ODR(d, m, beta0=, maxit=)` | `odr_fit(..., beta0=, maxit=)` | Flat signature, no intermediate objects. |
| `set_job(fit_type=0, deriv=0)` | `task="explicit-ODR", diff_scheme="forward"` | Literal strings, not integer flags. |
| `out.beta`, `out.sum_square` | `out.beta`, `out.sum_square` | OdrResult exposes same attribute names — passthrough. |

`set_job` is the subtle one — pyeq3 always calls it with the same constants, so "explicit-ODR" + "forward" is always correct for this codebase. Sites that don't call `set_job` (none in pyeq3, but worth confirming during port) would use odrpack's defaults.

### pyeq3 files touched

1. **`IModel.py`** — 7 references on lines 239, 241, 242 (first method) and 422, 424, 426, 427 (second method). Each method groups Model + Data (possibly with weights) + ODR + `run()`.
2. **`Services/SolverService.py`** — 6 references on lines 170, 172, 174, 180, 192, 212, all inside `SolveUsingODR` which has 3 retry branches. The `import scipy.interpolate, scipy.optimize, scipy.odr.odrpack` at line 13 becomes `import scipy.interpolate, scipy.optimize; import odrpack`.
3. **`UnitTests/Test_SolverService.py`** — 2 ODR tests (lines 19, 28) stay valid because they call `pyeq3.solverService().SolveUsingODR(model)` at the pyeq3 API level, not at the scipy layer. Internal mechanics change, external contract doesn't.

### WrapperForODR stays untouched

`IModel.WrapperForODR(self, inCoeffs, data)` is called from multiple places in pyeq3 including non-ODR code paths. Changing its signature would cascade. The adapter lives inline at each callsite as a tiny local `_f(x, beta): return inModel.WrapperForODR(beta, x)` closure.

## 5. Validation strategy

### Pre-port: numerical-equivalence fixture (throwaway)

Before any callsite changes:

1. Run a new script `UnitTests/_generate_odr_fixture.py` against the current `scipy.odr`-backed pyeq3. For each of ~5–10 datasets from `DataForUnitTests.py` (same ones `Test_SolverService` uses), call `SolveUsingODR` and capture the returned coefficients + final SSQ to a JSON file at `UnitTests/_odr_baseline_fixture.json`. Commit the fixture.

2. Keep `_generate_odr_fixture.py` importable but not part of `RunAllTests.py` — it's a one-shot snapshot generator.

### Port phase

3. Port `IModel.py` in commit **A**. Run `UnitTests/RunAllTests.py` — must stay green.
4. Port `Services/SolverService.py` in commit **B**. Run `UnitTests/RunAllTests.py` — must stay green.

### Post-port equivalence check

5. Add a temporary `UnitTests/Test_OdrEquivalence.py` that loads `_odr_baseline_fixture.json`, re-runs the same datasets through the ported `SolveUsingODR`, and asserts `numpy.allclose(ported_coeffs, baseline_coeffs, atol=1e-9, rtol=1e-9)` per fixture entry. Also assert `allclose` on final SSQ.
6. Run `RunAllTests.py` with this included. All pass → port is numerically equivalent.

### Integration

7. Tag `pyeq3ng v1.0.0-ng`, push.
8. In zunzunsite3, update `pyproject.toml` with `[tool.uv.sources]` block pinning to that tag. Run `uv lock` to pick it up.
9. Run `uv run pytest tests/ -v` — 78/78 must stay green (no odr tests there, but regressions elsewhere would surface).
10. Run `uv run python scripts/smoke_test.py` — 12/12 must stay green. FunctionFinder and polynomial fits exercise `curve_fit` paths that use `SolverService`; spline and characterize bypass ODR entirely; UDF sometimes picks `ODR` as fitting target when user selects it. At least one FunctionFinder-family scenario will touch SolveUsingODR.

### Cleanup

11. After at least one deliberate full smoke + UnitTests pass, delete:
    - `UnitTests/_generate_odr_fixture.py`
    - `UnitTests/_odr_baseline_fixture.json`
    - `UnitTests/Test_OdrEquivalence.py`
   Commit **C** removes them.
12. Merge the port branch into `main`, tag `v1.0.0-ng`. zunzun's pin already targets this tag.

## 6. Deliverables

### pyeq3ng repo (new)

- GitHub repository `github.com/<user>/pyeq3ng` seeded from upstream bitbucket (`https://bitbucket.org/zunzuncode/pyeq3.git`), with upstream preserved as a remote.
- Branch `main` contains the port. A working branch (e.g., `drop-scipy-odr`) handles the actual work in commits, merged back to `main` via fast-forward or `--no-ff` per preference.
- Tag `v1.0.0-ng` at the merge commit, marking the first "post-scipy.odr" release.
- README updated to note the fork provenance and the scipy.odr removal.
- No `setup.py`/`pyproject.toml` version bump dance — pyeq3 upstream never published to PyPI in the modern era (it's git-pinned by consumers like zunzun).

### zunzunsite3 repo (modified)

- `pyproject.toml`: add `[tool.uv.sources]` entry pinning pyeq3 to `pyeq3ng v1.0.0-ng` (or the equivalent commit SHA). Keep the `"pyeq3"` entry in `[project].dependencies` — `[tool.uv.sources]` is the resolver override, the dependency declaration still drives install.
- `uv.lock`: regenerated, records the git+commit pin.
- `CLAUDE.md`: short note in the Dependencies section — "pyeq3 is pinned to the pyeq3ng fork; see `docs/superpowers/specs/2026-04-20-pyeq3ng-odr-port-design.md` for rationale."
- `TODO.md`: strike-through the existing "pyeq3 imports scipy.odr" heading and insert a resolution block matching the pattern used by previously-closed entries on 2026-04-19 and 2026-04-20.

## 7. Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| odrpack produces coefficients outside the `allclose(atol=1e-9)` tolerance for some pyeq3 fit type. | Fixture-based equivalence test surfaces this pre-merge. If a fit type genuinely diverges, the fix is either a tolerance relaxation (documented, per-fit-type) or a pyeq3-side algorithmic adjustment. |
| odrpack's Fortran backend has different availability on Windows/macOS vs Linux (wheels missing for one platform). | Verified already — odrpack 0.5.0 installed cleanly on this Windows machine as a 17 MiB wheel. Before merge, verify the wheel is also available on Linux (`uv pip install odrpack` on a Linux VM or Codespace). If no wheel for a platform, Plan B reverts to pin `scipy<1.19`. |
| WrapperForODR has non-ODR callers that silently break from the arg-order swap I might do inadvertently. | The plan explicitly leaves WrapperForODR untouched — arg-order swap happens in per-callsite closures, not on the method itself. A grep for `WrapperForODR` before and after the port must show identical result sets. |
| zunzun's smoke doesn't actually exercise ODR fitting target (all existing scenarios use SSQABS). | Add one explicit-ODR scenario to smoke as part of this work OR verify that FunctionFinder's ranking phase internally uses SolveUsingODR. `SolverService.py:SolveUsingODR` is called when `inModel.fittingTarget == 'ODR'`. If smoke doesn't hit this code path post-port, the validation is incomplete. |
| 6-year-dormant upstream pyeq3 has other latent bugs we don't know about. | Out of scope. We're not trying to fix everything — just the scipy.odr time bomb. Other issues surface via future smoke failures. |

## 8. What we're NOT doing

- **Not submitting an upstream PR.** Upstream is dormant; the fork is permanent. If James Phillips ever revives pyeq3 we can revisit.
- **Not porting pyeq3 to Python 3.14 type hints or modernizing its structure.** Single-purpose branch: drop scipy.odr. Everything else stays.
- **Not changing zunzun's formConstants.targetList** — `'ODR'` stays a user-selectable fitting target. The port is transparent to users.
- **Not keeping a scipy<1.19 compatibility path in pyeq3ng.** It's a direct port; the `scipy.odr` imports are deleted, not conditional. Users who want scipy.odr compatibility should stay on upstream pyeq3 with a scipy pin.
- **Not pre-emptively adding an `ODR`-target scenario to zunzun smoke** unless the validation step reveals our existing scenarios don't exercise ODR. Decide during implementation after a per-scenario trace.

## 9. Timeline estimate

Ballpark across both repos:

- Fork + initial push + pre-port fixture: ~30 min
- IModel.py port: ~45 min
- SolverService.py port: ~60 min (9 callsites, 3 near-identical branches)
- Equivalence test + fixture rigging: ~30 min
- Full UnitTest run + fixture comparison iteration: ~30 min (plus any debugging drift this surfaces)
- zunzun pin update + smoke pass: ~30 min
- TODO close + CLAUDE.md note + cleanup commits: ~20 min

Total: ~4 hours of focused work. Call it one day with breaks.
