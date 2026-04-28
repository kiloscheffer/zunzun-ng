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

## Development quirks

- **`.venv/` must be excluded from cloud-sync clients (Dropbox, OneDrive, iCloud).** uv's default hardlink mode on Windows shares inodes between `.venv/` and the global uv cache (`%LOCALAPPDATA%\uv\cache\`). A sync client watching `.venv/` doubles the storage and breaks the hardlink relationship on cross-machine sync, silently corrupting Python imports (manifests as OS error 396 or hard-to-trace `ImportError`s). With the exclusion in place, no special handling is needed (verified 2026-04-28). If `.venv/` exclusion isn't configured, prefix `uv` commands with `UV_LINK_MODE=copy` as a workaround — at the cost of ~300-500 MB of duplicated packages per venv.
- **Cold-cache smoke flakiness.** The first smoke run after `rm -rf .venv && uv sync` (especially after a pyeq3 reinstall) can time out on 3D scenarios because spawn workers compile `.pyc` files on first import. Re-running on the warm venv passes. See the 4-worker-cap entry in `BACKLOG.md` for context.
- **`rm -rf .venv` may fail with "Device or resource busy"** on Windows when transient background processes (Dropbox indexers, Windows Search, etc.) hold handles open momentarily. PowerShell's `Remove-Item .venv -Recurse -Force` uses native Win32 calls and handles these gracefully where bash's `rm -rf` (via MSYS POSIX-emulation) does not. After deletion, `uv sync` rebuilds cleanly. Avoid running pytest + smoke in parallel right after a `uv lock` that changed any source URL — they'll race for cache locks.

## Dependencies

Python deps are declared in `pyproject.toml` and pinned in the committed `uv.lock`. Runtime group: Django (pinned `>=6.0,<6.1`), django-ratelimit, pyeq3, scipy, matplotlib, numpy, reportlab, psutil, beautifulsoup4, lxml, waitress. Dev group: mypy, pytest, pytest-django, requests.

**Django version.** Django 6.0 (short-term support, EOL ~December 2026). Next LTS is 6.2, expected April 2027. The code uses only long-stable APIs (`re_path`, `render`, the `TEMPLATES` settings shape, default `JSONSerializer` for sessions). Migration history: `docs/superpowers/specs/2026-04-18-django-upgrade-design.md` (2.2 → 5.2) and `docs/superpowers/specs/2026-04-19-django-6-upgrade-design.md` (5.2 → 6.0 + Python 3.11 → 3.14).

**FunkLoad is not in pyproject.toml.** Its `setup.py` uses `ez_setup`, which was removed from modern setuptools, so it cannot be installed under the uv-managed Python 3.14 environment. If you need to run the FunkLoad suite, use a separate legacy Python env, or port the HTTP assertions in `funkload_tests/test_Simple.py` to pytest + `requests` (the logic is just GET/POST with string-match assertions).

**No non-Python runtime deps.** Earlier versions required `imagemagick` and `gifsicle` system binaries for animated GIF output; as of 2026-04-19 those paths are pure-Python via matplotlib's `PillowWriter`. See `docs/superpowers/specs/2026-04-19-pillow-gif-design.md` for the migration history.

**pyeq3 fork.** `pyeq3` is pinned to `pyeq3-ng` (`github.com/kiloscheffer/pyeq3-ng`, tag `v1.0.0-ng`) via `[tool.uv.sources]` in `pyproject.toml`. The fork replaces `scipy.odr` (deprecated in scipy 1.17, slated for removal in 1.19) with the independent `odrpack` package on PyPI. Neither the original pyeq3 (bitbucket `zunzuncode`, dormant since 2020-01) nor the active PyPI-published fork (`github.com/equations-project/pyeq3`) has addressed this; pyeq3-ng is a permanent fork. See `docs/superpowers/specs/2026-04-20-pyeq3ng-odr-port-design.md` for migration rationale.

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
- Platform-specific calls (load average, process priority, zombie reap, shellouts for mogrify/gifsicle/rm) live in `zunzun/platform_compat.py`. Never call `os.getloadavg`, `/proc`, `vmstat`, or `os.popen` directly from view or LRP code — extend `platform_compat` instead.
- `get_parallel_process_count()` in `platform_compat.py` is platform-aware: fork platforms use ~80 MB per-worker memory estimate and cap at `cpu_count`; spawn platforms use ~750 MB and hard-cap at 4 workers because each spawned Pool worker re-imports numpy/scipy/pyeq3 from scratch.
- `CommonToAllViews()` calls `platform_compat.reap_completed_children()` on every request (no-op on Windows, proper cleanup on Unix). `HomePageView` spawns a daemon housekeeping child to clear expired sessions and trim `temp/` when it exceeds `MAX_TEMP_DIR_SIZE_IN_MBYTES` (default 500).
- **`os.fork()` and `os._exit()` no longer appear in the codebase.** Adding them will break Windows compatibility; prefer `multiprocessing.Process(spawn)` and plain `return` respectively. A `fork-pattern-reviewer` subagent in `.claude/agents/` audits for accidental regressions.

### Three parallel session stores per user

`LongRunningProcessView` lazily creates three separate `SessionStore`s and stashes their keys in the main request session:

- `session_key_status` — progress/status displayed by `StatusView`.
- `session_key_data` — solved coefficients, equation name/family, etc., consumed later by `EvaluateAtAPointView`.
- `session_key_functionfinder` — ranked results for `FunctionFinder`.

Session values are stored as JSON-native Python types (floats, strings, lists of floats, nested dicts of primitives) via the default `JSONSerializer`. The helpers `SaveDictionaryOfItemsToSessionStore` / `LoadItemFromSessionStore` in `StatusMonitoredLongRunningProcessPage.py` wrap `session.save()` in a SQLite-lock retry loop and handle the three-store routing (status / data / functionfinder). Callers are responsible for casting numpy values to plain Python primitives at write time — see `_json_native` in that same module.

**SQLite lock retry idiom**: every `session.save()` is wrapped in a `while not save_complete` loop that retries 100× at 10Hz before re-raising. When adding new session writes, copy this pattern — concurrent spawn children fighting for the SQLite session DB will lock it otherwise. Spawn children open fresh DB connections (vs. fork's inherited ones), so lock contention is arguably more relevant post-migration, not less.

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

### `temp/` is both scratch and static

`STATIC_URL = '/temp/'` and `STATICFILES_DIRS = (TEMP_FILES_DIR,)` — generated PDFs, graphs, and animations are served as static files from the same directory they are written to by child processes. `static_images/` (logo, favicon) lives there too. Do **not** add a separate static-files pipeline; the home-page cleanup logic assumes everything in `temp/` is disposable output.

### `pid_trace.py` is dormant by design

Both functions in `zunzun/LongRunningProcess/pid_trace.py` `return` at the top. The calls scattered through `StatusMonitoredLongRunningProcessPage.py` are debugging hooks that are no-ops in production. To enable per-fork trace files, remove the early `return`s; don't remove the call sites.

## Conventions

- **Feature branches with `--no-ff` merges.** Every non-trivial change goes through a feature branch and merges to master with `--no-ff`, preserving topology in `git log --first-parent`. Recent merge commits on master are templates for the commit-message structure (rationale, scope, verification, references to specs/plans).
- **Historical specs and plans freeze their names.** Files under `docs/superpowers/specs/` and `docs/superpowers/plans/` keep their original names through any rename; only the *live surface* (active code, current docs, live identifiers) gets updated. RESOLVED entries in `BACKLOG.md` similarly preserve names that were current at resolution time — those documents describe work done under those names.
- **Bulk `replace_all` is unsafe when a substring spans live identifiers AND historical filename references.** Use targeted Edit calls instead. Real example: `pyeq3ng → pyeq3-ng` over-substituted into a comment referencing the historical filename `pyeq3ng-odr-port-design.md` (commit `b1936c5`'s sloppy moment, fixed in `2ebff08`).

## Settings that must be filled before deploy

`settings.py` ships with empty placeholders for `SECRET_KEY`, `EXCEPTION_EMAIL_ADDRESS`, `FEEDBACK_EMAIL_ADDRESS`, `EMAIL_HOST_USER`, and `EMAIL_HOST_PASSWORD`. Email sending is gated on these being truthy (see `FeedbackView`, the exception handler in `LongRunningProcessView`), so leaving them blank silently disables email rather than crashing.

## Rate limiting

Views are decorated with `@ratelimit(key='ip', rate='12/m', block=False)` from `django-ratelimit`. `request.limited` is set to `True` when the caller exceeds the rate; `CommonToAllViews` applies a 5-second `time.sleep` when this is set. The limiter is always in effect (no install-time gating); to disable it for local testing, set `RATELIMIT_ENABLE = False` in `settings.py`.
