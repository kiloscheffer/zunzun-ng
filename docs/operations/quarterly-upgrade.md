# Quarterly dependency upgrade

A recurring maintenance procedure to keep zunzun-ng's dependencies current
and prevent the kind of accumulated decay that turns a "minor refresh" into
a multi-day archaeological dig (the experience that motivated the original
2026-04 modernization cycle).

**Cadence:** quarterly (every ~3 months). More frequent is churn; less
frequent risks a year's worth of small breakages stacking into one large
migration.

**Goal:** `uv.lock` reflects the latest versions that still pass our test
suite, with every floor and ceiling in `pyproject.toml` still honored.

---

## Pre-flight checks

1. Ensure you're on a clean master:

    ```bash
    git checkout master
    git pull origin master
    git status -sb        # expect: ## master...origin/master, no unstaged changes
    ```

2. Verify CI is currently green for the master HEAD. Either look at the
   GitHub Actions tab on github.com/kiloscheffer/zunzun-ng or run locally:

    ```bash
    UV_LINK_MODE=copy uv run pytest tests/ -v          # expect 78/78
    UV_LINK_MODE=copy uv run python scripts/smoke_test.py  # expect SMOKE OK
    ```

   If anything is red BEFORE the upgrade, fix that first — don't compound
   failures. A red-before-upgrade state usually points at infrastructure drift
   that's separable from the version bump.

---

## The upgrade

1. Create a feature branch:

    ```bash
    git checkout -b quarterly-upgrade-$(date +%Y-%m)
    ```

2. Run the upgrade — pulls the latest version of every package within its
   declared bounds, recomputes transitive dependencies, and updates
   `uv.lock`:

    ```bash
    UV_LINK_MODE=copy uv lock --upgrade
    ```

3. Inspect what moved:

    ```bash
    git diff uv.lock | grep -E '^[+-]version' | head -50
    ```

   For any package with a major or minor bump (not just patch), skim its
   changelog. Quick sanity check; not a deep dive. Things to watch:

    - Deprecation warnings in the changelog → may surface as test warnings.
    - Removed APIs in the changelog → may break our code if we use them.
    - "Breaking changes" sections → read carefully even if version says minor.

4. Run the test suite against the new versions:

    ```bash
    UV_LINK_MODE=copy uv sync                              # install the bumps
    UV_LINK_MODE=copy uv run pytest tests/ -v              # expect 78/78
    UV_LINK_MODE=copy uv run python scripts/smoke_test.py  # expect SMOKE OK
    ```

   Notes on expectations:

    - Pytest count may differ from 78 if tests have been added since the last
      upgrade. The relevant gate is "no regressions vs. previous run."
    - Watch for new warnings in pytest output. Even if tests pass, warnings
      foreshadow next quarter's pain (e.g., the pyeq3 SyntaxWarning fixed
      in v1.0.1-ng was visible as `1 warning` for months before becoming a
      hard SyntaxError in a future Python).
    - Smoke cold-cache flakiness on first run after a fresh pyeq3 install is
      a documented phenomenon in `MEMORY.md`
      (`project_3d_fit_slow_on_windows`) — re-run if a 3D scenario times
      out on first try.

---

## Outcome A — green

Commit, merge, push, cleanup:

```bash
git add uv.lock
git commit -m "Quarterly upgrade: $(date +%Y-%m)"  # body summarizes major bumps
git checkout master
git merge --no-ff quarterly-upgrade-$(date +%Y-%m) \
    -m "Merge quarterly-upgrade-$(date +%Y-%m): dependency refresh"
git push origin master
git branch -d quarterly-upgrade-$(date +%Y-%m)
```

The commit body should capture the user-facing summary — which packages
moved by minor/major version, any new warnings observed, etc. Future-you
reading `git log --oneline` six quarters later wants to see the cadence
clearly.

---

## Outcome B — red

Tests fail or smoke fails. Two paths forward, depending on the diagnosis:

### Path 1: fix forward

The upgrade revealed a real coupling we can patch:

1. Identify the failing test, assertion, or scenario.
2. Read the changelog for the package(s) most likely involved.
3. Patch the code, add a regression test if appropriate, and document the
   coupling in `pyproject.toml` (potentially with a new floor and a
   comment explaining what behavior is required).
4. Commit the fix together with the lockfile update; don't separate them.

Example: a numpy 2.5 release changes the dtype-promotion rules in a way
that breaks one of our fits. We patch `FittingBaseClass.py` to use the
new semantics, add a comment explaining the coupling, and the lockfile
keeps numpy 2.5 in.

### Path 2: revert and pin

The upgrade introduced a regression that's not worth fixing now:

1. Revert the lockfile change:

    ```bash
    git checkout uv.lock
    ```

2. Add an explicit upper-bound constraint in `pyproject.toml` to prevent
   the bad version from being picked up next quarter:

    ```toml
    "matplotlib>=3.2,<3.11"   # 3.11 broke our histogram density semantics; revisit when fixed
    ```

3. Re-run lock to pick up the new constraint:

    ```bash
    UV_LINK_MODE=copy uv lock
    ```

4. Document the exclusion in a comment with the issue link, commit hash,
   or symptom showing the regression. The constraint is doing real
   protective work; it must explain itself.

Example: pillow 13 deprecates an API matplotlib uses, breaking our
animations. Pin `pillow<13` with a comment, plan to revisit after
matplotlib catches up.

---

## Watch list per quarter

When running the upgrade, pay extra attention to:

- **Major bumps to numpy, scipy, matplotlib, Django.** These have the worst
  track record of breaking changes. Already floored and ceilinged in
  `pyproject.toml` to catch breaks early, but a major-version bump signal
  warrants a careful changelog read.
- **Python EOL dates.** Python 3.14 ≈ October 2030. Django 6.0 STS ≈
  December 2026 (next LTS 6.2 ≈ April 2027). Plan migrations 6 months
  before EOL — they're substantive enough to warrant their own
  spec/plan cycle, not a quarterly.
- **New major versions of (none) packages** — pillow, lxml, requests,
  beautifulsoup4, psutil, reportlab, mypy. If a major bump appears,
  consider whether a defensive ceiling is now warranted (the comments
  in `pyproject.toml` document the current "no constraint" rationale;
  re-evaluate it in light of the new release's changelog).
- **The `pyeq3-ng` companion fork.** Track its tags at
  `github.com/kiloscheffer/pyeq3-ng/releases`. If a new tag exists, bump
  the pin in `pyproject.toml`'s `[tool.uv.sources]` and re-lock — same
  procedure as a regular dep, just with a git-tag pin instead of a
  PyPI version.

---

## When to escalate (don't auto-execute as a quarterly)

Some upgrades warrant a full design + plan cycle, not a one-shot
quarterly:

- **Python migration** (e.g., 3.14 → 3.16 LTS in April 2027).
- **Django LTS migration** (6.x → 6.2 LTS or later).
- **A dep where a major bump removes APIs we use** (the pyeq3 →
  pyeq3-ng `scipy.odr` work was this shape).
- **Any change that affects the cross-platform spawn architecture** —
  these have ecosystem-wide implications and are well outside quarterly
  scope.

These follow the project's standard pattern documented in adjacent
specs/plans: design under `docs/superpowers/specs/`, implementation
plan under `docs/superpowers/plans/`, feature branch with explicit
verification, then `--no-ff` merge.

---

## CI-side check

`.github/workflows/ci.yml` runs pytest + smoke on every push, every PR,
and weekly on Mondays at 06:00 UTC. The weekly run catches platform-
specific drift (GitHub runner image updates, transitive dep silent
bumps, etc.) without you having to run anything.

If a weekly run fails but the previous weekly run on the same commit
passed, that's your signal that something in the runtime infrastructure
shifted — typically a wheel disappeared, a transitive dep silently
bumped, or a CI runner base image got updated. Investigation usually
points at one of the unconstrained-by-design (none) packages and may
warrant adding a defensive ceiling.

CI uses `uv sync --frozen` (locked-state-as-truth). The quarterly
procedure above is the *only* mechanism that actually moves the lock —
CI's role is verification, not refresh.
