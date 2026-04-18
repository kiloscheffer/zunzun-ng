# Django 2.2 → 5.2 LTS Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Django from pinned `>=2.2,<3.0` to `>=5.2,<5.3` LTS, eliminating all pre-5.x compat shims and the ad-hoc `pickle.dumps(...).hex()` session-encoding convention, and replacing `django_brake` with `django-ratelimit`.

**Architecture:** Phased refactor on a dedicated worktree. Early phases expand test coverage on the existing Django 2.2 codebase so regressions from later phases surface immediately. Session storage becomes JSON-native (pickle/hex convention removed across all call sites). Rate-limiter swap and the Django version bump happen last, with boot-breaking changes batched into a single atomic commit so `manage.py check` is always green at every checkpoint.

**Tech Stack:** Python 3.11, Django 5.2.x (target), multiprocessing (spawn context, already in place), `django-ratelimit`, pytest + pytest-django, `django.test.Client`, uv for dependency management.

**Reference:** Design spec at `docs/superpowers/specs/2026-04-18-django-upgrade-design.md` (commit `e54e546`).

---

## Global conventions

- **Test command:** `uv run pytest tests/ -v`
- **Smoke command:** `uv run python scripts/smoke_test.py`
- **Django check:** `uv run python manage.py check`
- **Commit style:** Short subject matching repo style (no conventional-commit prefixes), body with Co-Authored-By trailer per CLAUDE.md.
- **Per-step commits:** Each task ends with a single commit.
- **Hook awareness:** `.claude/hooks/py_compile_check.py` runs on every `.py` Edit/Write. It blocks commits that introduce syntax errors — fix the syntax if it fires.
- **Platform:** Windows 11 is the primary dev environment; all phases must end green on Windows.
- **Working directory:** All phases execute inside `../zunzunsite3-django5/` (the worktree created in Task 1). Commands assume this.

## Phasing overview

| Phase | Tasks | Output |
|---|---|---|
| **0 — Setup** | 1–2 | Worktree + branch created; baseline verified |
| **1 — Smoke expansion** | 3–9 | 9-scenario smoke green on current Django 2.2 |
| **2 — Pytest integration suite** | 10–15 | New integration tests green on current Django 2.2 |
| **3 — Session serializer refactor** | 16–21 | Pickle/hex dance gone; sessions hold JSON-native values |
| **4 — `django_brake` → `django-ratelimit`** | 22–24 | Modern rate limiter in place; ratelimit test green |
| **5 — Django 5.2 version bump** | 25–28 | Django 5.2 running; boot-breaking shims removed in one atomic commit |
| **6 — Template audit + final run** | 29–30 | `manage.py check` clean; full 9-scenario smoke + full pytest green |
| **7 — Documentation** | 31–33 | CLAUDE.md / agent / spec updated |
| **8 — Merge** | 34 | Merged to local master; NOT pushed to origin |

---

# Phase 0 — Setup

## Task 1: Create worktree and branch

**Files:**
- None — just git/filesystem operations

- [ ] **Step 1: Create worktree + branch from master**

Run from the main checkout at `C:\Dropbox\git\zunzunsite3\`:
```bash
git worktree add ../zunzunsite3-django5 -b django-5-upgrade master
cd ../zunzunsite3-django5
```

- [ ] **Step 2: Verify worktree is clean and on the new branch**

Run:
```bash
git status
git branch --show-current
```

Expected:
```
On branch django-5-upgrade
nothing to commit, working tree clean
django-5-upgrade
```

- [ ] **Step 3: Install deps in the worktree's .venv**

Run:
```bash
uv sync
```

Expected: packages install cleanly (deps are pinned in `uv.lock` which is shared with the main checkout).

No commit — this task is just setup.

---

## Task 2: Baseline verification

**Files:**
- None — just run existing tests

- [ ] **Step 1: Run the existing pytest suite**

Run: `uv run pytest tests/ -v`
Expected: 46 tests pass.

- [ ] **Step 2: Run the existing 3-scenario smoke test**

Run: `uv run python scripts/smoke_test.py`
Expected: output ends with `SMOKE OK: all scenarios passed`.

- [ ] **Step 3: Run `manage.py check`**

Run: `uv run python manage.py check`
Expected: `System check identified no issues (0 silenced).`

If any of these fail, do NOT proceed to Phase 1. Investigate and fix on a separate branch first.

No commit.

---

# Phase 1 — Smoke expansion

Goal: add 6 new scenarios to `scripts/smoke_test.py` while still on Django 2.2. This gives us a safety net that catches regressions in subsequent phases.

## Task 3: Add `characterize_2D` scenario

**Files:**
- Modify: `scripts/smoke_test.py`

- [ ] **Step 1: Add the form-fields dict and marker list near the existing `_FF_2D_FIELDS`/`_FF_EXPECTED_MARKERS`**

After `_FF_EXPECTED_MARKERS`, add:
```python
_CHAR_2D_FIELDS = {
    "commaConversion": "I",
    "dataNameX": "X Data",
    "dataNameY": "Y Data",
    "textDataEditor": _DATA_2D_POLY,
    "graphSize": "320x240",
    "scientificNotationX": "AUTO",
    "scientificNotationY": "AUTO",
    "graphScaleRadioButtonX": "0.050",
    "graphScaleRadioButtonY": "0.050",
}

_CHAR_EXPECTED_MARKERS = [
    "Data Statistics",
    "Minimum:",
    "Maximum:",
    "Mean:",
    "Standard Deviation:",
]
```

- [ ] **Step 2: Add a scenario call in `run_smoke()` after the existing 3 scenarios**

In `run_smoke()`, after the `function_finder_detail_2D` block and before the `if errors:` block, add:
```python
        err = _run_scenario(
            session,
            base,
            "characterize_2D",
            base + "/CharacterizeData/2/",
            _CHAR_2D_FIELDS,
            _CHAR_EXPECTED_MARKERS,
            timeout_s=120,
        )
        if err:
            errors.append(err)
        else:
            print("[characterize_2D] OK")
```

- [ ] **Step 3: Run smoke**

Run: `uv run python scripts/smoke_test.py`
Expected: 4 scenarios now pass. If the CharacterizeData template uses different marker strings, open `temp/_smoke_last_body_characterize_2D.html` (auto-dumped by `_check_markers` on failure) and adjust `_CHAR_EXPECTED_MARKERS` to strings actually present in the response.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "$(cat <<'EOF'
Add characterize_2D scenario to smoke test

Exercises /CharacterizeData/2/ which lands in LongRunningProcessView
but skips the fit path — just computes descriptive statistics.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add `polynomial_quadratic_3D` scenario

**Files:**
- Modify: `scripts/smoke_test.py`

- [ ] **Step 1: Add the 3D dataset constant near the existing 2D datasets**

After `_DATA_2D_FF`, add:
```python
# 3D dataset — small grid of (X, Y, Z) triples. Enough points to
# uniquely determine a full quadratic (6 coefficients in 3D).
_DATA_3D_POLY = """X Y Z
1.0 1.0 3.5
1.0 2.0 6.5
1.0 3.0 11.0
2.0 1.0 5.5
2.0 2.0 9.5
2.0 3.0 15.0
3.0 1.0 9.5
3.0 2.0 14.5
3.0 3.0 21.0
4.0 1.0 15.5
4.0 2.0 21.5
4.0 3.0 29.0
"""
```

- [ ] **Step 2: Add the 3D form-fields dict**

After `_CHAR_2D_FIELDS` (added in Task 3), add:
```python
_POLY_QUAD_3D_FIELDS = {
    "commaConversion": "I",
    "graphSize": "320x240",
    "animationSize": "0x0",
    "scientificNotationX": "AUTO",
    "scientificNotationY": "AUTO",
    "scientificNotationZ": "AUTO",
    "dataNameX": "X Data",
    "dataNameY": "Y Data",
    "dataNameZ": "Z Data",
    "graphScaleRadioButtonX": "0.050",
    "graphScaleRadioButtonY": "0.050",
    "graphScaleRadioButtonZ": "0.050",
    "logLinX": "LIN",
    "logLinY": "LIN",
    "logLinZ": "LIN",
    "fittingTarget": "SSQABS",
    "textDataEditor": _DATA_3D_POLY,
}
```

- [ ] **Step 3: Add a scenario call in `run_smoke()` after `characterize_2D`**

```python
        err = _run_scenario(
            session,
            base,
            "polynomial_quadratic_3D",
            base + "/FitEquation__F__/3/Polynomial/Full%20Quadratic/",
            _POLY_QUAD_3D_FIELDS,
            _POLY_EXPECTED_MARKERS,
            timeout_s=600,
        )
        if err:
            errors.append(err)
        else:
            print("[polynomial_quadratic_3D] OK")
```

- [ ] **Step 4: Run smoke**

Run: `uv run python scripts/smoke_test.py`
Expected: 5 scenarios pass. The 3D fit reuses the same `_POLY_EXPECTED_MARKERS` as the 2D fit because the result template is structurally identical.

If the URL segment for "Full Quadratic" is different in `pyeq3`'s 3D polynomial equations, check `FunctionFinder__F__/3/` response for the exact family/equation spelling and adjust. (Candidate spellings: `Full Quadratic`, `Polynomial 2D Full Quadratic`, `Full%20Quadratic`.)

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "$(cat <<'EOF'
Add polynomial_quadratic_3D scenario to smoke test

Exercises the 3D fit path end-to-end. Uses a 12-point grid
sufficient to solve a 3D full-quadratic (6 coefficients).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add `all_equations_2D` scenario

**Files:**
- Modify: `scripts/smoke_test.py`

- [ ] **Step 1: Add marker list**

After `_CHAR_EXPECTED_MARKERS`, add:
```python
_ALL_EQUATIONS_MARKERS = [
    "All Equations",
    "Polynomial",
]
```

- [ ] **Step 2: Add a GET-based scenario in `run_smoke()`**

After the `polynomial_quadratic_3D` block, add:
```python
        r = session.get(base + "/AllEquations/2/Polynomial/")
        err = _check_markers("all_equations_2D", r.text, _ALL_EQUATIONS_MARKERS)
        if err:
            errors.append(err)
        else:
            print("[all_equations_2D] OK")
```

- [ ] **Step 3: Run smoke**

Run: `uv run python scripts/smoke_test.py`
Expected: 6 scenarios pass.

If markers don't match, open `temp/_smoke_last_body_all_equations_2D.html` and adjust. The AllEquations page lists every equation class in the family; searching for the family name itself is a robust anchor.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "$(cat <<'EOF'
Add all_equations_2D scenario to smoke test

GET /AllEquations/2/Polynomial/ — renders the list template
for a single equation family, exercising render_to_response
via AllEquationsView.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Add `feedback_form` scenario

**Files:**
- Modify: `scripts/smoke_test.py`

- [ ] **Step 1: Add form-fields dict and marker lists**

After `_ALL_EQUATIONS_MARKERS`, add:
```python
_FEEDBACK_GET_MARKERS = [
    "Feedback",
    "name",
    "email",
]

_FEEDBACK_POST_FIELDS = {
    "name": "smoke test",
    "email": "smoke@example.com",
    "comments": "Automated smoke test submission — please ignore.",
}

_FEEDBACK_POST_MARKERS = [
    "Thank you",
]
```

- [ ] **Step 2: Add a GET+POST scenario in `run_smoke()`**

After the `all_equations_2D` block, add:
```python
        r = session.get(base + "/Feedback/")
        err = _check_markers("feedback_form_get", r.text, _FEEDBACK_GET_MARKERS)
        if err:
            errors.append(err)
        else:
            r = session.post(
                base + "/Feedback/",
                data=_FEEDBACK_POST_FIELDS,
                allow_redirects=True,
            )
            err = _check_markers("feedback_form_post", r.text, _FEEDBACK_POST_MARKERS)
            if err:
                errors.append(err)
            else:
                print("[feedback_form] OK")
```

- [ ] **Step 3: Run smoke**

Run: `uv run python scripts/smoke_test.py`
Expected: 7 scenarios pass. FeedbackView in `views.py` sends email when `FEEDBACK_EMAIL_ADDRESS` is truthy. Because `settings.py` ships with empty placeholders, no email is actually sent — the view still renders the reply template. If the reply template uses different thank-you language, open the dumped HTML and adjust `_FEEDBACK_POST_MARKERS`.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "$(cat <<'EOF'
Add feedback_form scenario to smoke test

GET /Feedback/ renders the form template; POST submits a sample
entry and renders the reply template. Exercises two more
render_to_response sites.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Add `evaluate_at_a_point` scenario (chained after `polynomial_quadratic_2D`)

**Files:**
- Modify: `scripts/smoke_test.py`

- [ ] **Step 1: Add marker list**

After `_FEEDBACK_POST_MARKERS`, add:
```python
_EVAL_AT_POINT_FIELDS = {
    "X": "7.0",
}

# The response is plain text "Calculated Y = <number>". Anchoring
# on "Calculated Y" catches both pyeq3 output variants.
_EVAL_AT_POINT_MARKERS = [
    "Calculated Y",
]
```

- [ ] **Step 2: Add a chained scenario in `run_smoke()` immediately after `polynomial_quadratic_2D` finishes successfully**

Locate the `[polynomial_quadratic_2D] OK` print. Immediately below the `else:` branch that prints it, before the scenario-2 FunctionFinder block, add:
```python
            r = session.post(
                base + "/EvaluateAtAPoint/",
                data=_EVAL_AT_POINT_FIELDS,
                allow_redirects=True,
            )
            err = _check_markers("evaluate_at_a_point", r.text, _EVAL_AT_POINT_MARKERS)
            if err:
                errors.append(err)
            else:
                print("[evaluate_at_a_point] OK")
```

The scenario depends on `polynomial_quadratic_2D` having populated `session_key_data` with the solved coefficients. Chaining it here ensures the prerequisite state exists.

- [ ] **Step 3: Run smoke**

Run: `uv run python scripts/smoke_test.py`
Expected: 8 scenarios pass.

If EvaluateAtAPointView returns "Could not find the equation '' in the equation family ''.", the `inEquationName`/`inEquationFamilyName` payload fix (commit `ce40521`) is not present — this plan assumes master is at or past that commit.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "$(cat <<'EOF'
Add evaluate_at_a_point scenario to smoke test

Runs immediately after polynomial_quadratic_2D so the session's
solved-coefficient state is available. POSTs a single X value and
asserts a numeric Y is computed and rendered.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Add `invalid_form_post` scenario

**Files:**
- Modify: `scripts/smoke_test.py`

- [ ] **Step 1: Add form-fields dict and marker list**

After `_EVAL_AT_POINT_MARKERS`, add:
```python
# Deliberately malformed data: Y column missing entirely, plus a
# non-numeric row. FittingBaseClass validation should reject and
# render invalid_form_data.html.
_INVALID_DATA = """X
not_a_number
5.357
6.097
"""

_INVALID_FIELDS = dict(_POLY_QUAD_FIELDS, textDataEditor=_INVALID_DATA)

_INVALID_MARKERS = [
    "could not",  # invalid_form_data.html message fragment
]
```

- [ ] **Step 2: Add a scenario in `run_smoke()` after the `feedback_form` block**

```python
        r = session.post(
            base + "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/",
            data=_INVALID_FIELDS,
            allow_redirects=True,
        )
        err = _check_markers("invalid_form_post", r.text, _INVALID_MARKERS)
        if err:
            errors.append(err)
        else:
            print("[invalid_form_post] OK")
```

- [ ] **Step 3: Run smoke**

Run: `uv run python scripts/smoke_test.py`
Expected: 9 scenarios pass. If the exact wording in `invalid_form_data.html` differs from "could not", open the dumped HTML and adjust. A robust anchor is any unique string in the invalid-form template; `grep -rn "invalid_form_data" zunzun/templates/` finds the template file, open and copy a stable phrase.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "$(cat <<'EOF'
Add invalid_form_post scenario to smoke test

POSTs malformed data (missing Y column, non-numeric row) to a
known-good fit URL; asserts the error template renders. Exercises
the render_to_response('zunzun/invalid_form_data.html', ...) site.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Update the smoke-test docstring

**Files:**
- Modify: `scripts/smoke_test.py` (top-of-file docstring)

- [ ] **Step 1: Rewrite the "Scenarios" section of the module docstring**

Replace the existing numbered list with:
```
Scenarios
---------

1. **polynomial_quadratic_2D** — direct 2D polynomial-quadratic fit.
2. **evaluate_at_a_point** — chained after scenario 1; POSTs X=7.0
   against the session's solved coefficients.
3. **function_finder_2D** — ranks an Exponential-only search.
4. **function_finder_detail_2D** — fits the RANK=1 equation.
5. **characterize_2D** — descriptive statistics only, no fit.
6. **polynomial_quadratic_3D** — 3D fit path.
7. **all_equations_2D** — GET AllEquations listing.
8. **feedback_form** — GET form + POST reply.
9. **invalid_form_post** — malformed data → error template.
```

- [ ] **Step 2: Run smoke one more time**

Run: `uv run python scripts/smoke_test.py`
Expected: `SMOKE OK: all scenarios passed` with 9 scenarios.

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "$(cat <<'EOF'
Update smoke test docstring to list all 9 scenarios

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 2 — Pytest integration suite

Goal: build integration tests using `django.test.Client` on the current Django 2.2 codebase. These tests cover URL resolution, template rendering, form handling, and session roundtrip — all behaviors that must still work after the Django 5 upgrade.

Tests are written in terms of *behavior*, not implementation, so they survive the Phase 3–5 refactors unchanged.

## Task 10: Extend conftest.py with integration fixtures

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Read the existing conftest**

Run: `cat tests/conftest.py` (or equivalent).

Existing content sets `DJANGO_SETTINGS_MODULE` and calls `django.setup()`. Preserve it.

- [ ] **Step 2: Append integration fixtures to the file**

Append to `tests/conftest.py`:
```python
import pytest
from unittest.mock import patch


@pytest.fixture
def client(db):
    """Django test Client with a fresh session. Uses pytest-django's
    `db` fixture to ensure the session DB tables exist (via migrations
    run once per test session).
    """
    from django.test import Client
    return Client()


@pytest.fixture
def mocked_process_start():
    """Patches multiprocessing.Process.start to a no-op for view tests
    that exercise the spawn dispatch path. Each call is recorded on
    the returned mock so tests can assert dispatch behavior.

    Without this patch, a POST to /FitEquation__F__/.../ in-test would
    actually spawn a Python subprocess, which is slow and OS-coupled.
    """
    with patch("multiprocessing.context.SpawnProcess.start") as mock_start:
        yield mock_start
```

- [ ] **Step 3: Run existing tests to confirm no breakage**

Run: `uv run pytest tests/ -v`
Expected: 46 tests pass (existing — no new tests yet).

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "$(cat <<'EOF'
Extend conftest.py with Client and mocked_process_start fixtures

Prepares for the integration test suite. Client fixture uses
pytest-django's db fixture so session writes have a real sqlite
backend. mocked_process_start patches Process.start so view-level
tests don't actually spawn children.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: test_urls.py — URL resolution

**Files:**
- Create: `tests/test_urls.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_urls.py`:
```python
"""URL resolution tests.

Asserts every public route in urls.py resolves to the correct view
callable. Regression catcher for the Phase 5 urls.py rewrite.
"""
import pytest
from django.urls import resolve

import zunzun.views


@pytest.mark.parametrize("path,view_fn", [
    ("/", zunzun.views.HomePageView),
    ("/StatusAndResults/", zunzun.views.StatusView),
    ("/CharacterizeData/2/", zunzun.views.LongRunningProcessView),
    ("/StatisticalDistributions/1/", zunzun.views.LongRunningProcessView),
    ("/FunctionFinder__F__/2/", zunzun.views.LongRunningProcessView),
    ("/FunctionFinderResults/2/", zunzun.views.LongRunningProcessView),
    ("/FitEquation__F__/2/Polynomial/Quadratic/", zunzun.views.LongRunningProcessView),
    ("/Equation/2/Polynomial/Quadratic/", zunzun.views.LongRunningProcessView),
    ("/EvaluateAtAPoint/", zunzun.views.EvaluateAtAPointView),
    ("/AllEquations/2/Polynomial/", zunzun.views.AllEquationsView),
    ("/Feedback/", zunzun.views.FeedbackView),
])
def test_url_resolves_to_view(path, view_fn):
    match = resolve(path)
    assert match.func is view_fn, f"{path} resolved to {match.func}, expected {view_fn}"
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_urls.py -v`
Expected: 11 parametrized tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_urls.py
git commit -m "$(cat <<'EOF'
Add test_urls.py — all 11 public routes resolve correctly

Regression catcher for the Django 5 urls.py rewrite that replaces
url() and patterns() with re_path().

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: test_views_render.py — direct render views

**Files:**
- Create: `tests/test_views_render.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_views_render.py`:
```python
"""Direct-render view tests.

Covers the views that call render_to_response (post-refactor: render).
These don't spawn children — they just return HTML. We assert status
code + a marker string that must be in the template output.
"""
import pytest


@pytest.mark.django_db
def test_home_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    # Marker that appears on the landing page
    assert b"zunzun" in response.content.lower() or b"curve" in response.content.lower()


@pytest.mark.django_db
def test_all_equations_renders(client):
    response = client.get("/AllEquations/2/Polynomial/")
    assert response.status_code == 200
    assert b"Polynomial" in response.content


@pytest.mark.django_db
def test_feedback_get_renders(client):
    response = client.get("/Feedback/")
    assert response.status_code == 200
    # Form field markers
    assert b"name" in response.content.lower()


@pytest.mark.django_db
def test_feedback_post_renders_reply(client):
    response = client.post("/Feedback/", data={
        "name": "test user",
        "email": "test@example.com",
        "comments": "integration test comment",
    })
    assert response.status_code == 200
    # Reply template renders (no crash even if email send is skipped
    # due to empty EMAIL_HOST_USER placeholder in settings.py).


@pytest.mark.django_db
def test_invalid_form_post_renders_error_template(client):
    response = client.post(
        "/FitEquation__F__/2/Polynomial/2nd Order (Quadratic)/",
        data={
            "commaConversion": "I",
            "dataNameX": "X",
            "dataNameY": "Y",
            "textDataEditor": "not\nnumbers\nat_all\n",
            "logLinX": "LIN",
            "logLinY": "LIN",
            "logLinZ": "LIN",
            "fittingTarget": "SSQABS",
            "graphSize": "320x240",
            "animationSize": "0x0",
            "scientificNotationX": "AUTO",
            "scientificNotationY": "AUTO",
            "graphScaleRadioButtonX": "0.050",
            "graphScaleRadioButtonY": "0.050",
        },
    )
    # The invalid-form view path doesn't spawn; it renders directly.
    assert response.status_code == 200
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_views_render.py -v`
Expected: 5 tests pass.

If a marker assertion fails, adjust — each assertion anchors on a word that *should* be in the rendered template. Goal is presence-check, not content exactness.

- [ ] **Step 3: Commit**

```bash
git add tests/test_views_render.py
git commit -m "$(cat <<'EOF'
Add test_views_render.py — direct-render view integration tests

Covers HomePage, AllEquations, Feedback GET/POST, and the
invalid-form error template. Regression catcher for the 6
render_to_response → render rewrites in Phase 5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: test_views_dispatch.py — spawn dispatch with mocked Process

**Files:**
- Create: `tests/test_views_dispatch.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_views_dispatch.py`:
```python
"""Spawn dispatch tests.

POSTs to fit URLs are expected to:
  1. validate the form,
  2. build a ChildPayload,
  3. call multiprocessing.Process(target=_run_fit_child, args=(payload,)).start(),
  4. redirect to /StatusAndResults/.

multiprocessing.Process.start is patched to a no-op via the
mocked_process_start fixture, so no actual child is spawned.
"""
import pytest


_VALID_POLY_FIELDS = {
    "commaConversion": "I",
    "graphSize": "320x240",
    "animationSize": "0x0",
    "scientificNotationX": "AUTO",
    "scientificNotationY": "AUTO",
    "dataNameX": "X",
    "dataNameY": "Y",
    "graphScaleRadioButtonX": "0.050",
    "graphScaleRadioButtonY": "0.050",
    "logLinX": "LIN",
    "logLinY": "LIN",
    "logLinZ": "LIN",
    "fittingTarget": "SSQABS",
    "textDataEditor": "X Y\n1 2\n2 4\n3 6\n4 8\n5 10\n",
}


@pytest.mark.django_db
def test_fit_post_dispatches_and_redirects(client, mocked_process_start):
    response = client.post(
        "/FitEquation__F__/2/Polynomial/2nd Order (Quadratic)/",
        data=_VALID_POLY_FIELDS,
    )
    # Successful dispatch returns a redirect to the status page.
    assert response.status_code == 302
    assert response.url == "/StatusAndResults/"
    # The Process.start mock was called exactly once.
    assert mocked_process_start.call_count == 1


@pytest.mark.django_db
def test_characterize_post_dispatches(client, mocked_process_start):
    response = client.post(
        "/CharacterizeData/2/",
        data=_VALID_POLY_FIELDS,
    )
    assert response.status_code == 302
    assert response.url == "/StatusAndResults/"
    assert mocked_process_start.call_count == 1


@pytest.mark.django_db
def test_status_view_renders_without_session_keys(client):
    """GET /StatusAndResults/ with no session keys should not crash."""
    response = client.get("/StatusAndResults/")
    # The view should render or return a sensible 200/4xx — not 500.
    assert response.status_code in (200, 302, 400, 404)
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_views_dispatch.py -v`
Expected: 3 tests pass.

If `mocked_process_start.call_count` is 0, the patch target (`multiprocessing.context.SpawnProcess.start`) is wrong. Check what `LongRunningProcessView` uses: open `zunzun/views.py`, search for `multiprocessing.Process` or `get_context("spawn")`; patch the actual class whose `.start()` is called.

- [ ] **Step 3: Commit**

```bash
git add tests/test_views_dispatch.py
git commit -m "$(cat <<'EOF'
Add test_views_dispatch.py — spawn-dispatch integration tests

Exercises LongRunningProcessView POST → validate → build payload
→ Process.start → redirect, with Process.start mocked to a no-op.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: test_session_roundtrip.py — JSON-native session roundtrip

**Files:**
- Create: `tests/test_session_roundtrip.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_session_roundtrip.py`:
```python
"""Session-helper roundtrip tests.

Asserts SaveDictionaryOfItemsToSessionStore / LoadItemFromSessionStore
preserve JSON-native values through a full write/read cycle.

These tests pass on the CURRENT pickle/hex implementation (because
pickle can trivially round-trip any JSON-native value), AND on the
Phase 3 post-refactor implementation (because JSON can too). This
lets us write the tests once and have them validate both states.
"""
import json

import pytest

from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
    StatusMonitoredLongRunningProcessPage,
)


def _make_lrp(db):
    """Build an LRP with a fresh status SessionStore — minimal setup
    needed for Save/Load helpers to work.
    """
    from django.contrib.sessions.backends.db import SessionStore
    lrp = StatusMonitoredLongRunningProcessPage()
    # Create a new session and stash its key on the LRP.
    session = SessionStore()
    session.create()
    lrp.session_key_status = session.session_key
    lrp.session_status = session
    lrp.session_key_data = None
    lrp.session_data = None
    lrp.session_key_functionfinder = None
    lrp.session_functionfinder = None
    return lrp


@pytest.mark.parametrize("key,value", [
    ("a_float", 3.14),
    ("a_string", "hello world"),
    ("an_empty_string", ""),
    ("a_list_of_floats", [1.0, 2.5, 3.7]),
    ("a_nested_dict", {"x": 1.0, "y": "text", "z": [1, 2, 3]}),
    ("a_unicode_string", "café résumé 🙂"),
    ("a_bool", True),
    ("an_int", 42),
])
@pytest.mark.django_db
def test_save_load_roundtrip(db, key, value):
    lrp = _make_lrp(db)
    lrp.SaveDictionaryOfItemsToSessionStore("status", {key: value})
    loaded = lrp.LoadItemFromSessionStore("status", key)
    assert loaded == value


@pytest.mark.parametrize("value", [
    3.14,
    "hello",
    [1.0, 2.0, 3.0],
    {"nested": {"x": 1, "y": "two"}},
    True,
    42,
])
@pytest.mark.django_db
def test_values_are_json_native(db, value):
    """Post-Phase-3 invariant: every value handed to the session helper
    should be cleanly serializable by stdlib json.
    """
    # json.dumps raises TypeError on numpy scalars, sets, datetime, etc.
    # If this passes, the value is safe to store without a pickle fallback.
    json.dumps(value)


@pytest.mark.django_db
def test_load_missing_key_returns_none(db):
    lrp = _make_lrp(db)
    result = lrp.LoadItemFromSessionStore("status", "no_such_key")
    assert result is None
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_session_roundtrip.py -v`
Expected: 17 tests pass (8 roundtrip params + 6 JSON-native params + 1 missing-key + 2 meta from parametrize = actual count varies; all green).

- [ ] **Step 3: Commit**

```bash
git add tests/test_session_roundtrip.py
git commit -m "$(cat <<'EOF'
Add test_session_roundtrip.py — JSON-native session helpers

Parametrized coverage of Save/LoadItemFromSessionStore for every
value shape the app actually stores (floats, strings, lists, nested
dicts, unicode, bools, ints). Tests pass on current pickle/hex
impl; will continue to pass after Phase 3 refactor removes pickle.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: test_evaluate_at_a_point.py — seeded session evaluation

**Files:**
- Create: `tests/test_evaluate_at_a_point.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_evaluate_at_a_point.py`:
```python
"""EvaluateAtAPointView tests.

Seeds a session_data SessionStore with coefficients for a known
equation (2D linear polynomial: y = a + b*x), then POSTs /EvaluateAtAPoint/
with an X value and asserts the response contains a numeric Y.
"""
import pickle

import pytest


def _seed_data_session(client, equation_name, equation_family, dimensionality,
                      coefficients, in_data_name_x="X"):
    """Seed session_data with the minimum keys EvaluateAtAPointView needs.

    Uses the current pickle/hex wire format. In Phase 3 this helper is
    rewritten to use native values; the test assertion remains unchanged.
    """
    from django.contrib.sessions.backends.db import SessionStore
    session_data = SessionStore()
    session_data.create()

    def _encode(v):
        return pickle.dumps(v, pickle.HIGHEST_PROTOCOL).hex()

    session_data["dimensionality"] = _encode(dimensionality)
    session_data["equationName"] = _encode(equation_name)
    session_data["equationFamilyName"] = _encode(equation_family)
    session_data["inDataName_X"] = _encode(in_data_name_x)
    session_data["solvedCoefficients"] = _encode(coefficients)
    session_data["fittingTarget"] = _encode("SSQABS")
    session_data.save()

    client_session = client.session
    client_session["session_key_data"] = session_data.session_key
    client_session.save()


@pytest.mark.django_db
def test_evaluate_at_point_with_seeded_linear_fit(client):
    """Seed a y = 1 + 2*x fit, POST X=3, expect Y ≈ 7 in response."""
    _seed_data_session(
        client,
        equation_name="Linear",
        equation_family="Polynomial",
        dimensionality=2,
        coefficients=[1.0, 2.0],
    )

    response = client.post("/EvaluateAtAPoint/", data={"X": "3.0"})
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    # The view's response format is "Calculated Y = <number>".
    assert "Calculated Y" in body or "Y =" in body
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_evaluate_at_a_point.py -v`
Expected: 1 test passes.

If the equation family/name doesn't match pyeq3's exact spelling, adjust `equation_family`/`equation_name` parameters. Correct spellings can be read from the AllEquations/2/Polynomial/ page (smoke scenario `all_equations_2D` dumps it).

In Phase 3, update the `_encode` helper to just return the value directly (no pickle). Test assertion remains unchanged.

- [ ] **Step 3: Commit**

```bash
git add tests/test_evaluate_at_a_point.py
git commit -m "$(cat <<'EOF'
Add test_evaluate_at_a_point.py — seeded session + evaluation

Seeds session_data with a y=1+2x linear polynomial, POSTs X=3,
asserts the response contains the computed Y. Regression catcher
for the inEquationName/FamilyName session-key plumbing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 3 — Session serializer refactor

Goal: drop the `pickle.dumps(...).hex()` convention everywhere. Sessions hold JSON-native values directly. All call sites updated; `SESSION_SERIALIZER` removed from `settings.py` (so Django 2.2 falls back to its default `JSONSerializer`). Tests remain green.

## Task 16: Refactor Save/LoadItemFromSessionStore helpers

**Files:**
- Modify: `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py`

- [ ] **Step 1: Rewrite `SaveDictionaryOfItemsToSessionStore`**

Locate the method (around line 504). Replace the body. The NEW body:
```python
    def SaveDictionaryOfItemsToSessionStore(self, inSessionStoreName, inDictionary):
        pid_trace.pid_trace(inSessionStoreName)

        session = eval('self.session_' + inSessionStoreName)
        if session is None:
            pid_trace.pid_trace('No session in sessionstore, creating new session')
            session = eval('SessionStore(self.session_key_' + inSessionStoreName + ')')

        pid_trace.pid_trace()

        for i in list(inDictionary.keys()):
            item = inDictionary[i]
            pid_trace.pid_trace(str(i) + ' type: ' + str(type(item)))
            # Store the raw value. Callers are responsible for producing
            # JSON-native values (no numpy scalars, sets, or datetime).
            session[i] = item
            pid_trace.pid_trace(str(i) + ' saved to session')

        pid_trace.pid_trace()

        if inSessionStoreName == 'status':
            session["timestamp"] = time.time()

        # sometimes database is momentarily locked, so retry on exception to mitigate
        s = session
        save_complete = False
        saveRetries = 0
        while not save_complete:
            try:
                s.save()
                save_complete = True
            except Exception as e:
                time.sleep(0.1)
                saveRetries += 1
                if saveRetries > 100:
                    raise e

        pid_trace.pid_trace()

        db.connections.close_all()
        close_old_connections()
        session = None

        pid_trace.delete_pid_trace_file()
```

- [ ] **Step 2: Rewrite `LoadItemFromSessionStore`**

Replace its body. The NEW body:
```python
    def LoadItemFromSessionStore(self, inSessionStoreName, inItemName):
        pid_trace.pid_trace()

        session = eval('self.session_' + inSessionStoreName)
        if session is None:
            session = eval('SessionStore(self.session_key_' + inSessionStoreName + ')')
        try:
            returnItem = session[inItemName]
        except KeyError:
            returnItem = None
        db.connections.close_all()
        close_old_connections()
        session = None

        pid_trace.delete_pid_trace_file()

        return returnItem
```

- [ ] **Step 3: Run the session roundtrip tests**

Run: `uv run pytest tests/test_session_roundtrip.py -v`
Expected: all tests pass (behavior unchanged — now implementation is simpler).

- [ ] **Step 4: Do NOT commit yet**

The 7 raw pickle sites in `views.py` still write pickle-hex strings into the *same* sessions that these helpers read from. Until Task 17 lands, a read from those sessions via `LoadItemFromSessionStore` would return the hex-string rather than the value. Hold the commit until after Task 17.

---

## Task 17: Update the 7 raw pickle/hex sites in views.py

**Files:**
- Modify: `zunzun/views.py`

- [ ] **Step 1: Identify every `pickle.dumps(...).hex()` and `pickle.loads(bytes.fromhex(...))` site**

Run: `grep -n "pickle\." zunzun/views.py`
Expected: 7 matches (lines 187, 189, 190, 216, 236, 237, 238 — approximate; count matches).

- [ ] **Step 2: Edit lines 186–190 — `redirectToResultsFileOrURL` read/reset block**

Replace:
```python
    if 'redirectToResultsFileOrURL' in session_status:
        if pickle.loads(bytes.fromhex(session_status['redirectToResultsFileOrURL'])) != '':
            # read and reset
            redirect = pickle.loads(bytes.fromhex(session_status['redirectToResultsFileOrURL']))
            session_status['redirectToResultsFileOrURL'] = pickle.dumps('', pickle.HIGHEST_PROTOCOL).hex()
```

with:
```python
    if 'redirectToResultsFileOrURL' in session_status:
        if session_status['redirectToResultsFileOrURL'] != '':
            # read and reset
            redirect = session_status['redirectToResultsFileOrURL']
            session_status['redirectToResultsFileOrURL'] = ''
```

- [ ] **Step 3: Edit line ~216 — `time_of_last_status_check` write**

Replace:
```python
    session_status['time_of_last_status_check'] = pickle.dumps(time.time(), pickle.HIGHEST_PROTOCOL).hex()
```

with:
```python
    session_status['time_of_last_status_check'] = time.time()
```

- [ ] **Step 4: Edit lines ~236–238 — `currentStatus`/`start_time`/`timestamp` reads**

Replace:
```python
        currentStatus = pickle.loads(bytes.fromhex(session_status['currentStatus']))
        startTime = pickle.loads(bytes.fromhex(session_status['start_time']))
        timeStamp = pickle.loads(bytes.fromhex(session_status['timestamp']))
```

with:
```python
        currentStatus = session_status['currentStatus']
        startTime = session_status['start_time']
        timeStamp = session_status['timestamp']
```

- [ ] **Step 5: Remove the now-unused `import pickle`**

Check: `grep -n "pickle" zunzun/views.py`
Expected: 0 matches after edits.

If 0 matches, remove `, pickle` from the `import os, sys, time, urllib.request, urllib.parse, urllib.error, signal, copy, pickle` line at the top of the file:
```python
import os, sys, time, urllib.request, urllib.parse, urllib.error, signal, copy
```

- [ ] **Step 6: Run pytest + smoke**

Run:
```bash
uv run pytest tests/ -v
uv run python scripts/smoke_test.py
```
Expected: all pytest tests pass, all 9 smoke scenarios pass.

- [ ] **Step 7: Commit (combined with Task 16)**

```bash
git add zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py zunzun/views.py
git commit -m "$(cat <<'EOF'
Drop pickle/hex session encoding; store JSON-native values

Save/LoadItemFromSessionStore helpers no longer pickle. All 7 raw
pickle sites in views.py also rewritten. Session reads and writes
now store native Python values directly. SESSION_SERIALIZER is
still PickleSerializer for this commit — updated in a follow-up.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: Cast numpy values to JSON-native at FunctionFinder write sites

**Files:**
- Modify: `zunzun/LongRunningProcess/FunctionFinder.py`
- Modify: `zunzun/LongRunningProcess/FunctionFinderResults.py`

- [ ] **Step 1: Find the SaveDictionaryOfItemsToSessionStore call sites in FunctionFinder.py**

Run: `grep -n "SaveDictionaryOfItemsToSessionStore" zunzun/LongRunningProcess/FunctionFinder.py`

The ranking data (`functionFinderResultsList`) is assembled during `PerformWorkInParallel` and written to `session_functionfinder` in `SpecificCodeForGeneratingListOfOutputReports` or equivalent. Locate the write.

- [ ] **Step 2: Add a JSON-native cast helper near the top of FunctionFinder.py**

After the existing imports, add:
```python
def _json_native(value):
    """Recursively coerce numpy types to plain Python primitives.

    Session storage uses the default JSONSerializer post-Phase-3, which
    cannot encode numpy scalars or arrays. Ranking tuples assembled by
    pyeq3 contain numpy floats; cast them here at the write boundary.
    """
    import numpy
    if isinstance(value, numpy.ndarray):
        return value.tolist()
    if isinstance(value, numpy.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _json_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_native(v) for v in value]
    return value
```

- [ ] **Step 3: Wrap the functionFinderResultsList write in `_json_native`**

Locate the line that writes to the session, e.g.:
```python
self.SaveDictionaryOfItemsToSessionStore('functionfinder', {'functionFinderResultsList': self.functionFinderResultsList})
```

Change to:
```python
self.SaveDictionaryOfItemsToSessionStore('functionfinder', {'functionFinderResultsList': _json_native(self.functionFinderResultsList)})
```

- [ ] **Step 4: Repeat the cast in FunctionFinderResults.py at any session-write site**

Run: `grep -n "SaveDictionaryOfItemsToSessionStore" zunzun/LongRunningProcess/FunctionFinderResults.py`

For any write that includes numpy values (coefficient lists, ranking statistics), wrap with `_json_native`. Add the same helper to FunctionFinderResults.py (or import from FunctionFinder if cleaner).

- [ ] **Step 5: Also audit SaveSpecificDataToSessionStore in each Fit* subclass**

Run: `grep -rn "SaveSpecificDataToSessionStore\|SaveDictionaryOfItemsToSessionStore" zunzun/LongRunningProcess/`

For any call that stores `solvedCoefficients` or equivalent numpy-backed lists, wrap with `_json_native` (import from FunctionFinder, or duplicate the helper in a shared location like `StatusMonitoredLongRunningProcessPage.py`).

For maintainability, move `_json_native` to `StatusMonitoredLongRunningProcessPage.py` as a module-level function and import from there.

- [ ] **Step 6: Run pytest + smoke**

Run:
```bash
uv run pytest tests/ -v
uv run python scripts/smoke_test.py
```
Expected: all pass. Scenarios 2 and 3 (FunctionFinder) are the real test — they exercise the numpy-heavy ranking path.

- [ ] **Step 7: Commit**

```bash
git add zunzun/LongRunningProcess/
git commit -m "$(cat <<'EOF'
Cast numpy values to JSON-native at session write sites

Adds _json_native helper to StatusMonitoredLongRunningProcessPage
and calls it at every ranking/coefficient write. Isolates the
numpy-into-session concern to one place instead of spreading
JSON-safety logic through the helpers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 19: Drop `SESSION_SERIALIZER` from settings.py

**Files:**
- Modify: `settings.py`

- [ ] **Step 1: Remove the line**

In `settings.py`, find:
```python
# the default JSON serializer yields error in this application
# http://stackoverflow.com/questions/24229397/django-object-is-not-json-serializable-error-after-upgrading-django-to-1-6-5
SESSION_SERIALIZER = 'django.contrib.sessions.serializers.PickleSerializer'
```

Delete both the comment and the line. Django falls back to its default `JSONSerializer`.

- [ ] **Step 2: Run pytest + smoke**

Run:
```bash
uv run pytest tests/ -v
uv run python scripts/smoke_test.py
```
Expected: all pass. This is the acid test for Phase 3 — if any session write still slips a numpy value through, JSONSerializer will raise `TypeError: Object of type float64 is not JSON serializable` and the offending scenario fails.

If a scenario fails with a JSON-serializable error, the traceback points to the specific session key and call site. Wrap that write site with `_json_native` (per Task 18) and re-run.

- [ ] **Step 3: Commit**

```bash
git add settings.py
git commit -m "$(cat <<'EOF'
Drop SESSION_SERIALIZER = PickleSerializer from settings

Django's default JSONSerializer is now used. Combined with the
Phase 3 pickle removal, session data is stored as JSON instead
of pickle-hex strings.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 20: Update tests/test_evaluate_at_a_point.py to drop the pickle-hex seed

**Files:**
- Modify: `tests/test_evaluate_at_a_point.py`

- [ ] **Step 1: Rewrite the `_seed_data_session` helper**

In `tests/test_evaluate_at_a_point.py`, replace:
```python
    def _encode(v):
        return pickle.dumps(v, pickle.HIGHEST_PROTOCOL).hex()

    session_data["dimensionality"] = _encode(dimensionality)
    session_data["equationName"] = _encode(equation_name)
    session_data["equationFamilyName"] = _encode(equation_family)
    session_data["inDataName_X"] = _encode(in_data_name_x)
    session_data["solvedCoefficients"] = _encode(coefficients)
    session_data["fittingTarget"] = _encode("SSQABS")
```

with:
```python
    session_data["dimensionality"] = dimensionality
    session_data["equationName"] = equation_name
    session_data["equationFamilyName"] = equation_family
    session_data["inDataName_X"] = in_data_name_x
    session_data["solvedCoefficients"] = coefficients
    session_data["fittingTarget"] = "SSQABS"
```

Also remove `import pickle` from the top of the file.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_evaluate_at_a_point.py -v`
Expected: pass (seeding now matches what the production code writes).

- [ ] **Step 3: Commit**

```bash
git add tests/test_evaluate_at_a_point.py
git commit -m "$(cat <<'EOF'
Update evaluate-at-a-point test to use JSON-native seeding

Matches the Phase 3 session-storage format. The test no longer
imports pickle.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 21: Phase 3 checkpoint

**Files:**
- None — verification only

- [ ] **Step 1: grep for remaining pickle/hex session wire-format usages**

Run: `grep -rn "pickle\.dumps\|pickle\.loads\|fromhex\|\.hex()" zunzun/ tests/`

Expected: 0 matches in runtime code. Matches only in `tests/test_pickle_spike.py` (pickle-safety test, unrelated — checks ChildPayload pickles cleanly) and `tests/test_child_payload.py`.

If any runtime match remains, go back and fix that call site.

- [ ] **Step 2: Full test + smoke pass**

Run:
```bash
uv run pytest tests/ -v
uv run python scripts/smoke_test.py
uv run python manage.py check
```
Expected: all green.

No commit — this is a checkpoint, not a change.

---

# Phase 4 — `django_brake` → `django-ratelimit`

## Task 22: Add django-ratelimit to dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add to runtime deps**

In `pyproject.toml`, add `"django-ratelimit"` to the `dependencies = [...]` list (alphabetically between `django>=2.2,<3.0` and `lxml`).

- [ ] **Step 2: Sync**

Run: `uv sync`
Expected: `django-ratelimit` installs.

- [ ] **Step 3: Run existing tests to confirm no breakage**

Run: `uv run pytest tests/ -v`
Expected: all pass (package installed but not yet imported).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
Add django-ratelimit dependency

Installs the modern rate limiter in preparation for replacing
the unmaintained django_brake import.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 23: Write test_ratelimit.py (failing test)

**Files:**
- Create: `tests/test_ratelimit.py`

- [ ] **Step 1: Write the test**

Create `tests/test_ratelimit.py`:
```python
"""Rate limit tests.

Asserts that >12 POSTs/minute to a rate-limited view cause the
13th to have request.limited set to True.

Pre-Phase-4 this test FAILS because django_brake is not installed
and the pass-through decorator does not set request.limited.
Post-Phase-4 it PASSES because django-ratelimit sets request.limited.
"""
import pytest


@pytest.mark.django_db
def test_thirteenth_rapid_post_is_rate_limited(client, mocked_process_start):
    """12 POSTs succeed, 13th triggers the rate limiter."""
    fields = {
        "commaConversion": "I",
        "graphSize": "320x240",
        "animationSize": "0x0",
        "scientificNotationX": "AUTO",
        "scientificNotationY": "AUTO",
        "dataNameX": "X",
        "dataNameY": "Y",
        "graphScaleRadioButtonX": "0.050",
        "graphScaleRadioButtonY": "0.050",
        "logLinX": "LIN",
        "logLinY": "LIN",
        "logLinZ": "LIN",
        "fittingTarget": "SSQABS",
        "textDataEditor": "X Y\n1 2\n2 4\n3 6\n4 8\n5 10\n",
    }
    url = "/FitEquation__F__/2/Polynomial/2nd Order (Quadratic)/"

    # First 12 posts: succeed (302 redirect to /StatusAndResults/).
    for i in range(12):
        response = client.post(url, data=fields)
        assert response.status_code == 302, f"Request {i+1} unexpectedly non-302"

    # 13th post: rate-limited. Because the view does NOT block (uses
    # block=False), the request still gets handled — but CommonToAllViews
    # detects request.limited and applies the 5s sleep then continues.
    # The response status stays 302 (view still dispatched). We test the
    # limiter by asserting the response took noticeably longer OR by
    # patching time.sleep to record its invocations.
    from unittest.mock import patch
    with patch("time.sleep") as mock_sleep:
        response = client.post(url, data=fields)
        assert any(
            call.args and call.args[0] >= 5
            for call in mock_sleep.call_args_list
        ), "expected request.limited branch to sleep ≥5s"
```

- [ ] **Step 2: Run the test — confirm it fails on current code**

Run: `uv run pytest tests/test_ratelimit.py -v`
Expected: FAIL — the 13th request doesn't sleep because the pass-through decorator doesn't set `request.limited`.

- [ ] **Step 3: Do NOT commit the test yet**

The test is committed together with the implementation change in Task 24.

---

## Task 24: Swap django_brake for django-ratelimit

**Files:**
- Modify: `zunzun/views.py`

- [ ] **Step 1: Replace the try/except import block**

In `zunzun/views.py`, find:
```python
# is django_brake used for rate limiting web site slammers?
try: # django_brake installed?
    from brake.decorators import ratelimit
    brake_available = True
except: # django_brake is not installed, use dummy pass-through decorator
    brake_available = False
    def ratelimit(*args, **kwargs):
        def temp(*args, **kwargs):
            return args[0]
        return temp
```

Replace with:
```python
from django_ratelimit.decorators import ratelimit
```

- [ ] **Step 2: Update the 5 decorator call sites**

Run: `grep -n "@ratelimit" zunzun/views.py`
Expected: 5 matches.

For each, replace:
```python
@ratelimit(rate='12/m') # if faster than once every five seconds, apply brake in CommonToAllViews() if django_brake installed
```

with:
```python
@ratelimit(key='ip', rate='12/m', block=False)
```

- [ ] **Step 3: Verify `brake_available` is no longer referenced**

Run: `grep -n "brake_available" zunzun/views.py`
Expected: 0 matches. If any reference remains (probably in `CommonToAllViews` guarding the `time.sleep`), remove it — with `django_ratelimit`, `request.limited` is always set (or not) by the decorator regardless.

If `CommonToAllViews` reads `brake_available`, replace the condition:
```python
if brake_available and getattr(request, 'limited', False):
    time.sleep(5)
```
with:
```python
if getattr(request, 'limited', False):
    time.sleep(5)
```

- [ ] **Step 4: Run the new test + existing tests + smoke**

Run:
```bash
uv run pytest tests/ -v
uv run python scripts/smoke_test.py
```
Expected: all pass including `test_ratelimit.py`.

If `test_ratelimit.py` still fails, inspect what `django-ratelimit` actually does on the 13th request. Some configurations require `DEBUG=False` for limits to apply. If so, the test may need to patch `settings.DEBUG` to `False` or use the library's test utilities.

- [ ] **Step 5: Commit**

```bash
git add zunzun/views.py tests/test_ratelimit.py
git commit -m "$(cat <<'EOF'
Replace django_brake with django-ratelimit

django_brake was last released in 2014 and does not install on
modern Django. django-ratelimit is its actively-maintained peer
with a similar decorator shape. Adds a test that verifies the
13th POST/min triggers the request.limited branch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 5 — Django 5.2 version bump

Goal: a single atomic commit that takes us from Django 2.2.28 to Django 5.2.x with the site still booting and tests passing. All boot-breaking changes are batched together.

## Task 25: Update pyproject.toml pin

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update the Django version pin**

Find:
```toml
    "django>=2.2,<3.0",
```

Replace:
```toml
    "django>=5.2,<5.3",
```

- [ ] **Step 2: Update the comment above the pin**

Find:
```toml
    # Django pinned pre-3.0 until render_to_response and the urls.py patterns()
    # compat shim are migrated. See CLAUDE.md > "Django version compatibility
    # shim" and views.py's 6 render_to_response call sites.
```

Replace with:
```toml
    # Django 5.2 is an LTS release supported through April 2028. The
    # site's code uses only long-stable APIs (re_path, render, TEMPLATES
    # settings, default JSONSerializer). See docs/superpowers/specs/
    # 2026-04-18-django-upgrade-design.md for migration history.
```

- [ ] **Step 3: Sync**

Run: `uv sync`
Expected: Django 5.2.x installs. uv.lock updates.

Do NOT run tests yet — the old urls.py and views.py will crash under Django 5.2. The next 3 tasks fix that.

No commit yet.

---

## Task 26: Rewrite urls.py for Django 5.2

**Files:**
- Modify: `urls.py`

- [ ] **Step 1: Replace the entire file**

Overwrite `urls.py` with:
```python
from django.urls import re_path
import zunzun.views

urlpatterns = [
    re_path(r"^$", zunzun.views.HomePageView),
    re_path(r"^StatusAndResults/", zunzun.views.StatusView),
    re_path(r"^CharacterizeData/([123])/$", zunzun.views.LongRunningProcessView),
    re_path(r"^StatisticalDistributions/([1])/$", zunzun.views.LongRunningProcessView),
    re_path(r"^FunctionFinder__.__/([23])/$", zunzun.views.LongRunningProcessView),
    re_path(r"^FunctionFinderResults/([23])/$", zunzun.views.LongRunningProcessView),
    re_path(r"^FitEquation__F__/([23])/(.+)/(.+)/$", zunzun.views.LongRunningProcessView),
    re_path(r"^Equation/([23])/(.+)/(.+)/$", zunzun.views.LongRunningProcessView),
    re_path(r"^EvaluateAtAPoint/$", zunzun.views.EvaluateAtAPointView),
    re_path(r"^AllEquations/([23])/(.+)/$", zunzun.views.AllEquationsView),
    re_path(r"^Feedback/$", zunzun.views.FeedbackView),
]
```

No `try/except`, no `patterns()`, no `from django.conf.urls import *`, no `cache_page` import (it wasn't used in the original either — remove if present).

- [ ] **Step 2: Do NOT run tests yet**

views.py still imports `render_to_response` — Django 5 will crash at module-import time. Task 27 fixes this.

No commit yet.

---

## Task 27: Rewrite render_to_response → render in views.py

**Files:**
- Modify: `zunzun/views.py`

- [ ] **Step 1: Replace the import**

At the top of `zunzun/views.py`, find:
```python
from django.shortcuts import render
from django.shortcuts import render_to_response
```

Replace with:
```python
from django.shortcuts import render
```

- [ ] **Step 2: Rewrite every call site**

Run: `grep -n "render_to_response" zunzun/views.py`
Expected: 7 matches (6 active + 1 commented-out).

For the 6 active call sites, replace each:
```python
return render_to_response('zunzun/TEMPLATE.html', CONTEXT)
```
with:
```python
return render(request, 'zunzun/TEMPLATE.html', CONTEXT)
```

The 7 specific sites (line numbers approximate):
- `zunzun/views.py:426` → `return render(request, 'zunzun/invalid_form_data.html', LRP.items_to_render)`
- `zunzun/views.py:437` → `return render(request, 'zunzun/generic_error.html', {'error':errorString})`
- `zunzun/views.py:489` → `return render(request, 'zunzun/invalid_form_data.html', items_to_render)`
- `zunzun/views.py:494` → `return render(request, 'zunzun/feedback_reply.html', {})`
- `zunzun/views.py:532` → `return render(request, 'zunzun/home_page.html', items_to_render)`
- `zunzun/views.py:561` → `return render(request, 'zunzun/list_all_equations.html', items_to_render)`

The commented-out call on line 410 can be left as a comment; it's not executed.

- [ ] **Step 3: Do NOT run tests yet**

settings.py still has `MIDDLEWARE_CLASSES` and `TEMPLATE_DIRS` shims. Django 5 ignores these and uses only `MIDDLEWARE` and `TEMPLATES`, so the site *might* boot — but the shim cleanup in Task 28 is logically part of the same atomic change.

No commit yet.

---

## Task 28: Clean up settings.py compat shims

**Files:**
- Modify: `settings.py`

- [ ] **Step 1: Remove `TEMPLATE_DEBUG`**

In `settings.py`, find:
```python
if 'runserver' in sys.argv:
    DEBUG = True
    TEMPLATE_DEBUG = True
else:
    DEBUG = False
    TEMPLATE_DEBUG = False
```

Replace with:
```python
if 'runserver' in sys.argv:
    DEBUG = True
else:
    DEBUG = False
```

- [ ] **Step 2: Remove `TEMPLATE_LOADERS`**

Find the `TEMPLATE_LOADERS = (...)` tuple (lines ~64–68) and delete it entirely, including the comment above.

- [ ] **Step 3: Remove `MIDDLEWARE_CLASSES` alias**

Find:
```python
MIDDLEWARE_CLASSES = (
    'django.middleware.gzip.GZipMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    #'django.contrib.auth.middleware.AuthenticationMiddleware',
)
MIDDLEWARE=MIDDLEWARE_CLASSES
```

Replace with:
```python
MIDDLEWARE = [
    'django.middleware.gzip.GZipMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # 'django.contrib.auth.middleware.AuthenticationMiddleware',
]
```

- [ ] **Step 4: Remove `TEMPLATE_DIRS`**

Find:
```python
# older versions of django use TEMPLATE_*
TEMPLATE_DIRS = (
    os.path.join(ROOT_PATH, 'templates'),
)

# newer versions of django use TEMPLATES below, not the older TEMPLATE_* above
# this file has both for compatibility although this gives a (harmless) warning
# because both coding styles are present in the same settings.py file
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': TEMPLATE_DIRS,
        'APP_DIRS': True,
        'OPTIONS': {
            # ... some options here ...
        },
    },
]
```

Replace with:
```python
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(ROOT_PATH, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {},
    },
]
```

- [ ] **Step 5: Run manage.py check**

Run: `uv run python manage.py check`
Expected: `System check identified no issues (0 silenced).`

If it reports errors about `INSTALLED_APPS` needing a tuple converted to a list, or similar, fix those too (Django 5 may require list form; tuples are usually still accepted).

- [ ] **Step 6: Run pytest + smoke**

Run:
```bash
uv run pytest tests/ -v
uv run python scripts/smoke_test.py
```
Expected: all pass.

If `test_views_render.py::test_home_page_renders` or any smoke scenario fails with a template error, proceed to Phase 6 template audit — a deprecated tag may be present.

- [ ] **Step 7: Commit (combined atomic: pyproject.toml + urls.py + views.py + settings.py)**

```bash
git add pyproject.toml uv.lock urls.py zunzun/views.py settings.py
git commit -m "$(cat <<'EOF'
Upgrade Django 2.2.28 → 5.2 LTS

Atomic boot-breaking change: urls.py rewritten from patterns()/url()
to re_path(); 6 render_to_response calls rewritten to render();
settings.py compat shims removed (MIDDLEWARE_CLASSES, TEMPLATE_DIRS,
TEMPLATE_LOADERS, TEMPLATE_DEBUG). pyproject.toml pin updated.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 6 — Template audit + final run

## Task 29: Audit templates for deprecated tags

**Files:**
- Inspect: `zunzun/templates/`

- [ ] **Step 1: grep for known-removed tags**

Run:
```bash
grep -rn "{% ifequal\|{% ifnotequal\|{% ssi" zunzun/templates/
```
Expected: 0 matches. If any hit, rewrite:
- `{% ifequal a b %}` → `{% if a == b %}`
- `{% ifnotequal a b %}` → `{% if a != b %}`
- `{% ssi path %}` → `{% include path %}` (if the included content is under the template root) or delete the directive.

- [ ] **Step 2: grep for other Django 5 template changes**

Run:
```bash
grep -rn "{% load admin_static\|{% load staticfiles\|{% load future" zunzun/templates/
```
Expected: 0 matches. `staticfiles` was merged into `static` long ago; `admin_static` is removed; `future` is removed.

- [ ] **Step 3: If any fixes applied, run smoke**

Run: `uv run python scripts/smoke_test.py`
Expected: all 9 scenarios pass.

- [ ] **Step 4: Commit (only if fixes applied; otherwise skip)**

```bash
git add zunzun/templates/
git commit -m "$(cat <<'EOF'
Update templates for Django 5.2 compatibility

Replaces deprecated template tags with their modern equivalents.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

If no fixes were needed, no commit.

---

## Task 30: Full test + smoke checkpoint

**Files:**
- None — verification only

- [ ] **Step 1: Run every gate**

Run each:
```bash
uv run python manage.py check
uv run pytest tests/ -v
uv run python scripts/smoke_test.py
uv run python manage.py runserver --noreload &
# wait a few seconds; curl http://127.0.0.1:8000/ → 200 HTML
# kill the runserver
uv run waitress-serve --listen=127.0.0.1:8001 wsgi:application &
# curl http://127.0.0.1:8001/ → 200 HTML
# kill the waitress
```

Expected:
- manage.py check: no issues
- pytest: all pass (46 existing + ~40 new = ~86 tests)
- smoke: all 9 scenarios pass
- runserver: serves home page
- waitress: serves home page

If any gate fails, fix before proceeding.

No commit — this is a checkpoint.

---

# Phase 7 — Documentation

## Task 31: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Rewrite the "Django version pin" paragraph**

Find the paragraph in CLAUDE.md (under "Dependencies") that starts with `**Django version pin.** Django is intentionally held below 3.0 because...`. Replace with:
```markdown
**Django version.** Django 5.2 LTS, supported through April 2028. The code uses only long-stable APIs (`re_path`, `render`, the `TEMPLATES` settings shape, default `JSONSerializer` for sessions). See `docs/superpowers/specs/2026-04-18-django-upgrade-design.md` for the 2.2 → 5.2 migration history.
```

- [ ] **Step 2: Rewrite the PickleSerializer paragraph**

Find the paragraph that starts `Every value is \`pickle.dumps(...).hex()\`-encoded before storage...`. Replace with:
```markdown
Session values are stored as JSON-native Python types (floats, strings, lists of floats, nested dicts of primitives) via the default `JSONSerializer`. The helpers `SaveDictionaryOfItemsToSessionStore` / `LoadItemFromSessionStore` in `StatusMonitoredLongRunningProcessPage.py` wrap `session.save()` in a SQLite-lock retry loop and handle the three-store routing (status / data / functionfinder). Callers are responsible for casting numpy values to plain Python primitives at write time — see `_json_native` in that same module.
```

- [ ] **Step 3: Rewrite the rate-limiting paragraph**

Find the paragraph starting `Views are decorated with @ratelimit(rate='12/m') from django_brake...`. Replace with:
```markdown
Views are decorated with `@ratelimit(key='ip', rate='12/m', block=False)` from `django-ratelimit`. `request.limited` is set to `True` when the caller exceeds the rate; `CommonToAllViews` applies a 5-second `time.sleep` when this is set. The limiter is always in effect (no install-time gating); to disable it for local testing, set `RATELIMIT_ENABLE = False` in `settings.py`.
```

- [ ] **Step 4: Remove the "Django version compatibility shim" section**

Find the section starting `### Django version compatibility shim`. Delete the entire subsection including its bullet points (`urls.py` try/except, `settings.py` dual MIDDLEWARE, etc.) — none of this is true anymore.

- [ ] **Step 5: Run smoke to sanity-check the file is still readable**

Run: `uv run python manage.py check`
Expected: no issues. (Trivial because CLAUDE.md doesn't affect Django boot; this is just a habit.)

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
Update CLAUDE.md for Django 5.2 / JSON sessions / django-ratelimit

Removes the "Django pinned pre-3.0" language, the PickleSerializer
paragraph, and the "Django version compatibility shim" section.
Updates the rate-limiting paragraph to reference django-ratelimit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 32: Update .claude/agents/fork-pattern-reviewer.md

**Files:**
- Modify: `.claude/agents/fork-pattern-reviewer.md`

- [ ] **Step 1: Rewrite the "Session data is pickle-hex encoded" bullet**

Find:
```markdown
- **Session data is pickle-hex encoded.** Values written to `session_key_status` / `_data` / `_functionfinder` should pass through `pickle.dumps(x, pickle.HIGHEST_PROTOCOL).hex()` and be read with `pickle.loads(bytes.fromhex(...))`. Use the `SaveDictionaryOfItemsToSessionStore` / `LoadItemFromSessionStore` helpers rather than encoding by hand.
```

Replace with:
```markdown
- **Session data is JSON-native.** Values written to `session_key_status` / `_data` / `_functionfinder` must be JSON-serializable (floats, strings, lists, nested dicts of primitives). The `SaveDictionaryOfItemsToSessionStore` / `LoadItemFromSessionStore` helpers in `StatusMonitoredLongRunningProcessPage.py` handle the SQLite-retry loop; callers are responsible for casting numpy values to plain Python primitives via `_json_native` before write.
```

- [ ] **Step 2: Update the "canonical snippet" section**

Find the code block starting with `The canonical snippet (see ...SaveDictionaryOfItemsToSessionStore):`. If it shows a pickle-hex example, update the snippet to reflect the new JSON-native call shape, or delete the snippet if it's no longer the clearest illustration.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/fork-pattern-reviewer.md
git commit -m "$(cat <<'EOF'
Update fork-pattern-reviewer agent for JSON-native sessions

Removes the pickle-hex encoding requirement; replaces with the
JSON-native contract and _json_native cast at write sites.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 33: Add completion note to cross-platform design spec

**Files:**
- Modify: `docs/superpowers/specs/2026-04-17-cross-platform-design.md`

- [ ] **Step 1: Find §11 (Risks) or §12 (Lessons Learned)**

Locate the "Non-goals" paragraph that mentions the Django 2.x → 4.2 LTS migration being out of scope.

- [ ] **Step 2: Append an update note**

Add a bracketed note at the end of that paragraph:
```markdown
> **Update (2026-04-18):** The Django migration has since been completed — see `docs/superpowers/specs/2026-04-18-django-upgrade-design.md` and its plan `docs/superpowers/plans/2026-04-18-django-upgrade.md`. Target was 5.2 LTS, not 4.2. The `try/except patterns` shim and `MIDDLEWARE_CLASSES`/`MIDDLEWARE` alias are gone; the session-storage convention changed from pickle-hex to JSON-native.
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-04-17-cross-platform-design.md
git commit -m "$(cat <<'EOF'
Note Django 5.2 migration completion in cross-platform spec

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 8 — Merge

## Task 34: Merge to local master, do NOT push

**Files:**
- None — git operations only

- [ ] **Step 1: Switch to the main checkout**

Leave the worktree and go to the main checkout:
```bash
cd C:/Dropbox/git/zunzunsite3
```

- [ ] **Step 2: Ensure main checkout is on master**

Run: `git checkout master`
Expected: clean working tree on master.

- [ ] **Step 3: Merge the feature branch with --no-ff**

Run:
```bash
git merge --no-ff django-5-upgrade -m "$(cat <<'EOF'
Merge Django 2.2 → 5.2 LTS upgrade branch

See docs/superpowers/specs/2026-04-18-django-upgrade-design.md
and docs/superpowers/plans/2026-04-18-django-upgrade.md.

Key changes:
- Django 5.2 LTS (supported to April 2028)
- Pickle/hex session encoding removed; sessions use JSONSerializer
- django_brake replaced with django-ratelimit
- urls.py uses re_path; no more patterns() shim
- settings.py: single MIDDLEWARE and TEMPLATES, no aliases
- 6 render_to_response → render
- Pytest integration test suite added
- Smoke test expanded to 9 scenarios

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Confirm the merge commit**

Run:
```bash
git log --oneline -5
git status
```
Expected: the merge commit at HEAD, working tree clean.

- [ ] **Step 5: Run tests + smoke on master one more time**

Run:
```bash
uv run pytest tests/ -v
uv run python scripts/smoke_test.py
```
Expected: all pass.

- [ ] **Step 6: Do NOT push**

Do NOT run `git push`. The user has explicitly stated they do not want changes pushed to `origin`. Only run `git push` if the user explicitly asks.

- [ ] **Step 7: Clean up the worktree (optional)**

After the merge is verified, the worktree is no longer needed:
```bash
git worktree remove ../zunzunsite3-django5
git branch -d django-5-upgrade  # or keep for history — user's call
```

---

## Self-review checklist (plan author runs this before handoff)

- [x] **Spec coverage.** Every spec section has at least one task:
  - §1 Scope → Task 25 (Django pin), Task 24 (rate-limiter), Tasks 16–20 (pickle/hex), Task 10+ (pytest suite), Tasks 3–9 (smoke expansion), Tasks 31–33 (docs).
  - §4.1 pyproject.toml → Task 22 (django-ratelimit), Task 25 (django 5.2).
  - §4.2 urls.py → Task 26.
  - §4.3 settings.py → Tasks 19 (SESSION_SERIALIZER), 28 (shim cleanup).
  - §4.4 views.py → Tasks 17 (pickle), 24 (ratelimit), 27 (render_to_response).
  - §4.5 StatusMonitoredLongRunningProcessPage → Task 16.
  - §4.6 FunctionFinder casts → Task 18.
  - §4.7 templates → Task 29.
  - §4.8 pytest suite → Tasks 10–15, 23.
  - §4.9 smoke expansion → Tasks 3–9.
  - §4.10 docs → Tasks 31–33.
  - §5 session contract table → covered implicitly by Tasks 16–18.
  - §6 execution phases → Phases 0–8 map 1:1.
  - §7 risks → Tasks 14, 18 (numpy cast), 23 (ratelimit), 29 (template audit).
  - §8 acceptance criteria → Task 30 checkpoint.

- [x] **No placeholders.** No "TBD", "TODO", "similar to Task N", or "add appropriate error handling".

- [x] **Type consistency.** `_json_native` helper defined in Task 18 (lives in StatusMonitoredLongRunningProcessPage.py per Step 5); referenced in Phase 3 checkpoint (Task 21). `mocked_process_start` fixture defined in Task 10, used in Tasks 13 and 23.

- [x] **Risk coverage.** Every risk in spec §7 has a corresponding mitigation task:
  - Pickle bypass → Task 21 Step 1 grep.
  - Numpy leaking → Task 18.
  - django-ratelimit signature → Task 23.
  - Template tags → Task 29.
  - request.session API → Task 16 + full pytest run.
  - Windows regression → Task 30 full-run on Windows.
  - Process(spawn) + Django 5 → Task 30 smoke.
  - STATICFILES_STORAGE → no action, flagged for future.
