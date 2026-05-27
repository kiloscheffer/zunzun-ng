# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ZunZunNG is a Django site that performs 2D/3D nonlinear curve & surface fitting via the `pyeq3` library, with genetic-algorithm initial parameter estimation, PDF/animation output, and source-code generation in multiple languages.

It is a permanent fork of `bitbucket.org/zunzuncode/zunzunsite3` (James R. Phillips's Python 3 port of zunzun.com — see `LICENSE.txt` for the `Copyright (C) 2016 James R. Phillips` notice, retained under BSD-2-clause terms), modernized for Python 3.14 / Django 6.0, ported off `scipy.odr` via the `pyeq3-ng` fork, and made cross-platform (Linux, macOS, Windows) by replacing the original `os.fork()` architecture with `multiprocessing.Process(spawn)`. Hosted at `github.com/kiloscheffer/zunzun-ng`. The original bitbucket repo has been dormant since 2020.

**Identity-rename scope note.** The top-level project identity is ZunZunNG. The user-facing HTML templates (page titles, headers, about page) and PDF / graph watermark strings were updated to display ZunZunNG in commit `9d3ba63` (resolved entry in `BACKLOG.md`); James R. Phillips's original prose is preserved verbatim in `templates/zunzun/divs/about.html` per BSD-2-clause attribution. The Django app folder is still `zunzun/` (renaming it would churn ~every file path and add zero value).

## Running the site

### Development

```bash
uv sync                                   # one-time: create .venv, install deps
uv run python manage.py migrate           # one-time: creates the django_session table
uv run python manage.py runserver         # open http://127.0.0.1:8000/
```

### Production (cross-platform)

```bash
uv sync --no-dev
uv run waitress-serve --listen=127.0.0.1:8000 wsgi:application
```

See `docs/deployment/{linux,macos,windows}.md` for per-platform recipes (systemd unit, launchd plist, IIS + NSSM). Waitress replaced gunicorn/uwsgi as the recommended production server because it works natively on all three platforms.

The `session_db/db.sqlite3` file is gitignored — it gets created by `migrate` on first run. Without it, every session write from a spawned child fails because `django_session` doesn't exist.

`DEBUG` is toggled automatically by looking for `'runserver'` in `sys.argv` (see `settings.py`), so running under Waitress or WSGI disables debug regardless of env vars.

### End-to-end smoke test

```bash
uv run python scripts/smoke_test.py
```

Starts a throwaway Waitress, POSTs a 2D polynomial-quadratic fit, polls for completion, asserts structural markers in the result. Useful after a fresh clone or dep bump. Takes ~1–2 min on Linux, ~3–5 min on Windows.

## Operational gotchas

Read [`docs/internals/active-gotchas.md`](docs/internals/active-gotchas.md) before touching the corresponding area. Categories: environment & venv, spawn LRP pattern, sessions & state, templates & URLs, files & directories, filename grammar in `temp/`, FunkLoad legacy, deploy.

## Dependencies

Python deps are declared in `pyproject.toml` and pinned in the committed `uv.lock`. Runtime group: Django (pinned `>=6.0,<6.1`), django-ratelimit, pyeq3, scipy, matplotlib, numpy, reportlab, psutil, beautifulsoup4, lxml, waitress. Dev group: mypy, pytest, pytest-django, requests.

**Django version.** Django 6.0 (short-term support, EOL ~December 2026). Next LTS is 6.2, expected April 2027. The code uses only long-stable APIs (`re_path`, `render`, the `TEMPLATES` settings shape, default `JSONSerializer` for sessions). Migration history: `docs/superpowers/specs/2026-04-18-django-upgrade-design.md` (2.2 → 5.2) and `docs/superpowers/specs/2026-04-19-django-6-upgrade-design.md` (5.2 → 6.0 + Python 3.11 → 3.14).

**FunkLoad is not in pyproject.toml.** Its `setup.py` uses `ez_setup`, which was removed from modern setuptools, so it cannot be installed under the uv-managed Python 3.14 environment. If you need to run the FunkLoad suite, use a separate legacy Python env, or port the HTTP assertions in `funkload_tests/test_Simple.py` to pytest + `requests` (the logic is just GET/POST with string-match assertions).

**No non-Python runtime deps.** Earlier versions required `imagemagick` and `gifsicle` system binaries for animated GIF output; as of 2026-04-19 those paths are pure-Python via matplotlib's `PillowWriter`. See `docs/superpowers/specs/2026-04-19-pillow-gif-design.md` for the migration history.

**pyeq3 fork.** `pyeq3` is pinned to `pyeq3-ng` (`github.com/kiloscheffer/pyeq3-ng`) via `[tool.uv.sources]` in `pyproject.toml` — see that file for the exact tag. The fork replaces `scipy.odr` (deprecated in scipy 1.17, slated for removal in 1.19) with the independent `odrpack` package on PyPI. Neither the original pyeq3 (bitbucket `zunzuncode`, dormant since 2020-01) nor the active PyPI-published fork (`github.com/equations-project/pyeq3`) has addressed this; pyeq3-ng is a permanent fork. See `docs/superpowers/specs/2026-04-20-pyeq3ng-odr-port-design.md` for migration rationale.

## Tests

Two layers:

**Unit tests** in `tests/` run via pytest:

```bash
uv run pytest tests/ -v
```

78 tests cover `zunzun/platform_compat.py` (load-avg shim, parallel-process count, subprocess wrapper, binary availability), `ChildPayload` round-trip, pickle-safety of every concrete `LRP` subclass's payload, URL routing, view-render integration, and session round-trip. Runs in ~20 seconds; no server required.

**End-to-end smoke** in `scripts/smoke_test.py` runs the full stack:

```bash
uv run python scripts/smoke_test.py
```

Starts Waitress, POSTs a 2D polynomial-quadratic fit against sample data, polls `/StatusAndResults/` until completion, asserts on structural markers in the result. Takes ~1–5 min depending on platform.

**FunkLoad (legacy)** in `funkload_tests/` is not runnable under the current uv-managed environment — its `setup.py` uses `ez_setup`, removed from modern setuptools. Its assertion strings are also stale under modern numpy/scipy/pyeq3. The folder is preserved as historical reference; do not invest in re-running it. Port individual assertions to pytest or to the smoke script if needed.

**CI.** `.github/workflows/ci.yml` runs pytest on Linux/macOS/Windows and smoke on Linux for every push, every PR, and weekly (Monday 06:00 UTC). Uses `uv sync --frozen` so CI verifies the locked state still installs and runs on each platform — drift detection through a passive heartbeat. See `docs/operations/quarterly-upgrade.md` for the recurring dependency-upgrade procedure that *moves* the lock (CI never does, it only verifies).

## Architecture

### Unusual project layout

Unlike a normal Django project, there is **no inner project package** — `settings.py`, `urls.py`, `wsgi.py`, and `manage.py` sit at the repo root next to the single Django app `zunzun/`. `DJANGO_SETTINGS_MODULE` is just `'settings'`. When touching imports, note that `zunzun/*` does `import settings` directly (not `from project import settings`).

### The spawn-based long-running-process pattern

This is the single most important thing to understand before modifying views or session code.

1. A POST to `/CharacterizeData/`, `/FitEquation__F__/...`, `/FunctionFinder__.__/...`, etc. lands in `LongRunningProcessView` (`zunzun/views.py`).
2. That view picks a concrete `LRP` class from `zunzun/LongRunningProcess/` by **substring-matching `request.path`** (e.g. `'UserDefinedFunction'` → `FitUserDefinedFunction`, `'Spline'` → `FitSpline`, else `FitOneEquation`). To add a new fit flow, both a URL pattern in `urls.py` and a new branch in this dispatcher are required.
3. The view calls `LRP.build_child_payload()` to produce a picklable `ChildPayload` snapshot (session keys, dimensionality, renice level, data_object, equation, subclass-specific `extra` dict). See `zunzun/LongRunningProcess/child_payload.py`.
4. The parent calls `multiprocessing.Process(target=_run_fit_child, args=(payload,))` using the **spawn** start method (mandatory on Windows, safest on all platforms under multi-threaded WSGI servers like Waitress). The parent returns `HttpResponseRedirect('/StatusAndResults/')`.
5. The child — a fresh Python interpreter — calls `django.setup()`, imports the LRP class from `payload.lrp_class_path`, calls `apply_child_payload()` to hydrate state, runs `PerformAllWork()`, and returns. Exceptions are logged to `temp/{pid}.log` and a user-visible status is written to the session.
6. `StatusView` polls every 3s via `<meta http-equiv=REFRESH>`; when the child writes `redirectToResultsFileOrURL` into the status session, `StatusView` serves the generated file or issues a redirect.

Consequences:
- **The site runs on Linux, macOS, and Windows.** Waitress is the recommended cross-platform WSGI server; see `docs/deployment/`.
- Platform-specific calls (load average, process priority, zombie reap, shellouts for mogrify/gifsicle/rm) live in `zunzun/platform_compat.py`.
- `CommonToAllViews()` calls `platform_compat.reap_completed_children()` on every request (no-op on Windows, proper cleanup on Unix). `HomePageView` spawns a daemon housekeeping child to clear expired sessions and trim `temp/` when it exceeds `MAX_TEMP_DIR_SIZE_IN_MBYTES` (default 500).
- Operational rules for this pattern (no direct `os.fork`/`os.getloadavg` calls, the 4-worker spawn cap, the SQLite-retry idiom, etc.) live in `docs/internals/active-gotchas.md`.

### Three parallel session stores per user

`LongRunningProcessView` lazily creates three separate `SessionStore`s and stashes their keys in the main request session:

- `session_key_status` — progress/status displayed by `StatusView`.
- `session_key_data` — solved coefficients, equation name/family, etc., consumed later by `EvaluateAtAPointView`.
- `session_key_functionfinder` — ranked results for `FunctionFinder`.

The helpers `SaveDictionaryOfItemsToSessionStore` / `LoadItemFromSessionStore` in `StatusMonitoredLongRunningProcessPage.py` handle the three-store routing (status / data / functionfinder) and the SQLite-lock retry pattern on `save()`. Session values must be JSON-native (the default `JSONSerializer` is used). See `docs/internals/active-gotchas.md` § Sessions and state for the retry idiom and the numpy-casting requirement.

### ChildPayload contract

When adding a new `LRP` subclass, override `build_child_payload()` / `apply_child_payload()` in addition to `PerformAllWork` and friends. The contract:

- `build_child_payload()` runs in the PARENT, reads `self.boundForm.equation.X` and other request-bound state, writes primitive values into `payload.extra[...]`.
- `apply_child_payload(payload)` runs in the CHILD (where `boundForm` doesn't exist), reads from `payload.extra[...]` and writes to `self.dataObject.equation.X` or `self`.
- Both call `super()` first.
- Any attribute set on `self` between form processing and the fit dispatch must be explicitly carried. This includes `pdfTitleHTML`, `webFormName`, `rank`, and fit-specific flags like `splineOrderX`.

The existing `StatusMonitoredLongRunningProcessPage.build_child_payload` and `FittingBaseClass.build_child_payload` handle the common subset. Subclasses extend `payload.extra` for their unique fields. See `zunzun/LongRunningProcess/child_payload.py` for the dataclass definition and `_run_fit_child` entrypoint.

### `LongRunningProcess` class hierarchy

```
StatusMonitoredLongRunningProcessPage   # base: session I/O, PDF canvas, parallel-pool sizing
    └── FittingBaseClass                # adds equation/data validation, form binding
            ├── FitOneEquation          # default fit path
            ├── FitSpline
            ├── FitUserDefinedFunction
            ├── FitUserCustomizable/SelectablePolynomial / Polyfunctional / Rational
            ├── FunctionFinder          # ranks many equations in parallel
            └── FunctionFinderResults
    ├── CharacterizeData                # statistics only (no fit)
    └── StatisticalDistributions
```

`PerformAllWork()` on the base class drives the lifecycle: `GenerateListOfWorkItems` → `PerformWorkInParallel` → `ReportsAndGraphs` → PDF → write redirect to session. Subclasses override the first two.

### `commonproblems/` (vendored static content, served at `/CommonProblems/`)

`commonproblems/` at the project root (lowercase, Unix-conventional dir name) holds a vendored copy of `bitbucket.org/zunzuncode/CommonProblems` (James R. Phillips's "Common Problems" reference site — animated confidence-interval visualizations of curve-fitting failure modes). 53 files: 9 HTML pages, 22 PNG stills, 16 animated GIFs, 2 generation scripts, plus `LICENSE` (BSD-2-clause) and `DEDICATION.txt`. Upstream is dormant since 2020-01; vendoring follows the same pattern as the `pyeq3-ng` companion fork — preserve a snapshot under our umbrella with attribution intact.

Served at `/CommonProblems/` via the `urls.py` static() helper in DEBUG mode and via nginx/IIS in production (see `docs/deployment/`). Internal links inside the vendored content are all relative (`<a href="Outlier_A.html">`), so the content works wherever it's mounted. URL-case and bare-slash gotchas live in `docs/internals/active-gotchas.md` § Templates and URLs.

### `static/` (committed assets) vs `temp/` (runtime outputs)

Two separate directories serve two separate URL prefixes:

- **`static/`** at the project root holds committed assets that ship with the codebase: jQuery, favicon, logos, `custom.css`. Tracked in git, served at `STATIC_URL = '/static/'` via `django.contrib.staticfiles` (auto-served by `runserver` in DEBUG, by nginx/IIS in production).
- **`temp/`** at the project root holds runtime-generated outputs: PDFs, error plots, surface animations written by spawned fit children. Gitignored except for a `.gitkeep` placeholder, served at `MEDIA_URL = '/temp/'` (dev: explicit `urlpatterns += static(MEDIA_URL, ...)` block in `urls.py`; production: nginx/IIS direct file serving). Auto-trimmed by `HomePageView`'s housekeeping when total size exceeds `MAX_TEMP_DIR_SIZE_IN_MBYTES` (default 500).

For Python-side filesystem paths to static assets (e.g., the PDF watermark logo), use `settings.STATIC_FILES_DIR` (= `BASE_DIR/static`). For paths to runtime outputs, `settings.TEMP_FILES_DIR` (= `BASE_DIR/temp` and also `MEDIA_ROOT`). The split landed in the 2026-04-28 static-files restructure; before that, both lived under `temp/static_images/` and `temp/` with `STATIC_URL = '/temp/'`.

### Coefficient-picker templates (`polyfunctional` / `polyrational` / `polynomial_customization`)

`templates/zunzun/divs/{polyfunctional,polyrational,polynomial_customization}_selection_div.html` share the same scaffolding: `.matrix-layout` CSS grid for 3D (with `.label-y` / `.label-x` axis labels), `.function-matrix` cell styling, `.function-matrix-scroll` horizontal-overflow wrapper, and `<h4>` section labels. When touching one for layout/styling, evaluate whether the change applies to all three.

The cells in these templates have a load-bearing JS coupling — see `docs/internals/active-gotchas.md` § Templates and URLs before touching cell `id` or inline `style`.

## Conventions

- **Feature branches with `--no-ff` merges.** Every non-trivial change goes through a feature branch and merges to main with `--no-ff`, preserving topology in `git log --first-parent`. Recent merge commits on main are templates for the commit-message structure (rationale, scope, verification, references to specs/plans).
- **Conventional Commits + Conventional Branches.** Commit subjects follow the `type: subject` shape with allowed types `feat`/`fix`/`docs`/`style`/`refactor`/`perf`/`test`/`build`/`ci`/`chore`/`revert`; branch names start with `feature/`/`bugfix/`/`hotfix/`/`release/`/`chore/`/`feat/`/`fix/`. The rules live in `cchk.toml` (single source of truth) and are enforced on every PR by `.github/workflows/commit-check.yml`. Bot PRs (Dependabot, Renovate) skip the branch check because their branch names don't match. The merge subject convention `Merge feat/<branch>` is exempt (it's a merge commit; `allow_merge_commits = true`).
- **Historical specs and plans freeze their names.** Files under `docs/superpowers/specs/` and `docs/superpowers/plans/` keep their original names through any rename; only the *live surface* (active code, current docs, live identifiers) gets updated. RESOLVED entries in `BACKLOG.md` similarly preserve names that were current at resolution time — those documents describe work done under those names.
- **Bulk `replace_all` is unsafe when a substring spans live identifiers AND historical filename references.** Use targeted Edit calls instead. Real example: `pyeq3ng → pyeq3-ng` over-substituted into a comment referencing the historical filename `pyeq3ng-odr-port-design.md` (commit `b1936c5`'s sloppy moment, fixed in `2ebff08`).
- **Agent PR-creation gate.** `gh pr create` is denied by a PreToolUse hook (`.claude/hooks/gh_pr_create_gate.py`) unless a per-HEAD marker exists at `$(git rev-parse --git-common-dir)/.code-review-passed-$(git rev-parse HEAD)`. The gate is invisible to humans (only fires on agent Bash tool calls). To satisfy: run `/code-review` (or `/code-review:code-review`) against the diff vs origin/main, address any Critical findings, `touch` the marker (full 40-char SHA required), then retry `gh pr create`. New commits invalidate the marker.

## Settings that must be filled before deploy

`settings.py` ships with empty placeholders for `SECRET_KEY`, `EXCEPTION_EMAIL_ADDRESS`, `FEEDBACK_EMAIL_ADDRESS`, `EMAIL_HOST_USER`, and `EMAIL_HOST_PASSWORD`. Email sending is gated on these being truthy (see `FeedbackView`, the exception handler in `LongRunningProcessView`), so leaving them blank silently disables email rather than crashing.

## Rate limiting

Views are decorated with `@ratelimit(key='ip', rate='12/m', block=False)` from `django-ratelimit`. `request.limited` is set to `True` when the caller exceeds the rate; `CommonToAllViews` applies a 5-second `time.sleep` when this is set. The limiter is always in effect (no install-time gating); to disable it for local testing, set `RATELIMIT_ENABLE = False` in `settings.py`.
