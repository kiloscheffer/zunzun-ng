# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ZunZunSite3 is a Django site that performs 2D/3D nonlinear curve & surface fitting via the `pyeq3` library, with genetic-algorithm initial parameter estimation, PDF/animation output, and source-code generation in multiple languages. It is a Python 3 port of the original zunzun.com.

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

## Dependencies

Python deps are declared in `pyproject.toml` and pinned in the committed `uv.lock`. Runtime group: Django (pinned `>=2.2,<3.0` — see "Django version pin" below), pyeq3, scipy, matplotlib, numpy, reportlab, psutil, beautifulsoup4, lxml, waitress. Dev group: mypy, pytest, pytest-django, requests.

**Django version pin.** Django is intentionally held below 3.0 because `render_to_response` (removed in Django 3.0) is called in 6 places in `zunzun/views.py`, and `url()` / the `patterns()` compat shim in `urls.py` break on Django 4.0+. Upgrading to modern Django LTS is a tracked but separate piece of work — see `.claude/agents/fork-pattern-reviewer.md` for the review standards and plan the migration as its own branch.

**FunkLoad is not in pyproject.toml.** Its `setup.py` uses `ez_setup`, which was removed from modern setuptools, so it cannot be installed under the uv-managed Python 3.11 environment. If you need to run the FunkLoad suite, use a separate legacy Python env, or port the HTTP assertions in `funkload_tests/test_Simple.py` to pytest + `requests` (the logic is just GET/POST with string-match assertions).

**System dependencies** (not Python packages, not managed by uv): `imagemagick` and `gifsicle`. See `README.txt`.

## Tests

Two layers:

**Unit tests** in `tests/` run via pytest:

```bash
uv run pytest tests/ -v
```

40 tests cover `zunzun/platform_compat.py` (load-avg shim, parallel-process count, subprocess wrapper, binary availability), `ChildPayload` round-trip, and pickle-safety of every concrete `LRP` subclass's payload. Runs in ~2 seconds; no server required.

**End-to-end smoke** in `scripts/smoke_test.py` runs the full stack:

```bash
uv run python scripts/smoke_test.py
```

Starts Waitress, POSTs a 2D polynomial-quadratic fit against sample data, polls `/StatusAndResults/` until completion, asserts on structural markers in the result. Takes ~1–5 min depending on platform.

**FunkLoad (legacy)** in `funkload_tests/` is not runnable under the current uv-managed environment — its `setup.py` uses `ez_setup`, removed from modern setuptools. Its assertion strings are also stale under modern numpy/scipy/pyeq3. The folder is preserved as historical reference; do not invest in re-running it. Port individual assertions to pytest or to the smoke script if needed.

## Architecture

### Unusual project layout

Unlike a normal Django project, there is **no inner project package** — `settings.py`, `urls.py`, `wsgi.py`, and `manage.py` sit at the repo root next to the single Django app `zunzun/`. `DJANGO_SETTINGS_MODULE` is just `'settings'`. When touching imports, note that `zunzun/*` does `import settings` directly (not `from project import settings`).

### Django version compatibility shim

The code is written to run across a broad span of Django versions:
- `urls.py` has a `try: patterns(...) except: [url(...), ...]` split.
- `settings.py` defines **both** `MIDDLEWARE_CLASSES` and `MIDDLEWARE` (aliased), **both** `TEMPLATE_DIRS` and `TEMPLATES`. The duplication is intentional — don't "clean it up."

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

Every value is `pickle.dumps(...).hex()`-encoded before storage and `pickle.loads(bytes.fromhex(...))` on read — because `SESSION_SERIALIZER` is set to `PickleSerializer` but the data still has to survive a JSON round-trip in places. Use the helpers `SaveDictionaryOfItemsToSessionStore` / `LoadItemFromSessionStore` in `StatusMonitoredLongRunningProcessPage.py` rather than writing session keys directly; they handle the hex/pickle dance and SQLite-lock retries.

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

## Settings that must be filled before deploy

`settings.py` ships with empty placeholders for `SECRET_KEY`, `EXCEPTION_EMAIL_ADDRESS`, `FEEDBACK_EMAIL_ADDRESS`, `EMAIL_HOST_USER`, and `EMAIL_HOST_PASSWORD`. Email sending is gated on these being truthy (see `FeedbackView`, the exception handler in `LongRunningProcessView`), so leaving them blank silently disables email rather than crashing.

## Rate limiting

Views are decorated with `@ratelimit(rate='12/m')` from `django_brake`. If `brake` isn't installed, `views.py` substitutes a pass-through decorator — so decorator presence does not imply the limit is actually enforced. `CommonToAllViews` applies a 5-second `time.sleep` when `request.limited` is set, which only happens when `brake` is present.
