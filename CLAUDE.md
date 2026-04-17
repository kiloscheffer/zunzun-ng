# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ZunZunSite3 is a Django site that performs 2D/3D nonlinear curve & surface fitting via the `pyeq3` library, with genetic-algorithm initial parameter estimation, PDF/animation output, and source-code generation in multiple languages. It is a Python 3 port of the original zunzun.com.

## Running the site

Only a development server is defined; there is no build step and no `manage.py test` target.

```bash
python3 manage.py migrate        # one-time: creates the django_session table
python3 manage.py runserver      # open http://127.0.0.1:8000/
```

The `session_db/db.sqlite3` file is gitignored — it gets created by `migrate` on first run. Without it, every session write from a forked child fails because `django_session` doesn't exist.

`DEBUG` is toggled automatically by looking for `'runserver'` in `sys.argv` (see `settings.py`), so running under WSGI disables debug regardless of env vars.

External dependencies are not in a `requirements.txt`; see `README.txt` — notably `pyeq3` (pip), `reportlab`, `psutil`, plus system packages `imagemagick` and `gifsicle`.

## Tests

Tests are **functional load tests** (FunkLoad), not `unittest` suites managed by Django. They run against a live server:

```bash
cd funkload_tests
fl-run-test -v test_Simple.py Simple.test_simple          # full suite
fl-run-test -v test_Characterizer2D.py                    # single file
fl-run-test -v test_Simple.py Simple.test_simple -d       # debug mode
```

The test server URL lives in `funkload_tests/Simple.conf` under `[main] url=`. Individual assertions in `test_Simple.py` are gated by module-level booleans (`testPolynomialQuadratic2D_SSQABS = True`, etc.) — flip those rather than writing new files to toggle pieces.

## Architecture

### Unusual project layout

Unlike a normal Django project, there is **no inner project package** — `settings.py`, `urls.py`, `wsgi.py`, and `manage.py` sit at the repo root next to the single Django app `zunzun/`. `DJANGO_SETTINGS_MODULE` is just `'settings'`. When touching imports, note that `zunzun/*` does `import settings` directly (not `from project import settings`).

### Django version compatibility shim

The code is written to run across a broad span of Django versions:
- `urls.py` has a `try: patterns(...) except: [url(...), ...]` split.
- `settings.py` defines **both** `MIDDLEWARE_CLASSES` and `MIDDLEWARE` (aliased), **both** `TEMPLATE_DIRS` and `TEMPLATES`. The duplication is intentional — don't "clean it up."

### The fork-based long-running-process pattern

This is the single most important thing to understand before modifying views or session code.

1. A POST to `/CharacterizeData/`, `/FitEquation__F__/...`, `/FunctionFinder__.__/...`, etc. lands in `LongRunningProcessView` (`zunzun/views.py`).
2. That view picks a concrete `LRP` class from `zunzun/LongRunningProcess/` by **substring-matching `request.path`** (e.g. `'UserDefinedFunction'` → `FitUserDefinedFunction`, `'Spline'` → `FitSpline`, else `FitOneEquation`). To add a new fit flow, both a URL pattern in `urls.py` and a new branch in this dispatcher are required.
3. The view calls `os.fork()`. The **parent** returns `HttpResponseRedirect('/StatusAndResults/')`. The **child** calls `LRP.PerformAllWork()`, writes progress/results to the session DB, and exits via `os._exit(0)`.
4. `StatusView` (also in `views.py`) polls every 3s via an `<meta http-equiv=REFRESH>`; when the child writes `redirectToResultsFileOrURL` into the status session, `StatusView` either serves the generated file or issues a redirect.

Consequences:
- **The site cannot run on Windows or uwsgi.** Only mod_wsgi / gunicorn / the dev server on Linux work (see README.txt).
- `GetParallelProcessCount()` in `StatusMonitoredLongRunningProcessPage.py` shells out to `vmstat` and reads `/proc/loadavg` — Linux-only and hard-coded.
- `CommonToAllViews()` reaps zombie children via `psutil` on every request; `HomePageView` also forks a housekeeping child to clear expired sessions and trim `temp/` when it exceeds `MAX_TEMP_DIR_SIZE_IN_MBYTES` (default 500).

### Three parallel session stores per user

`LongRunningProcessView` lazily creates three separate `SessionStore`s and stashes their keys in the main request session:

- `session_key_status` — progress/status displayed by `StatusView`.
- `session_key_data` — solved coefficients, equation name/family, etc., consumed later by `EvaluateAtAPointView`.
- `session_key_functionfinder` — ranked results for `FunctionFinder`.

Every value is `pickle.dumps(...).hex()`-encoded before storage and `pickle.loads(bytes.fromhex(...))` on read — because `SESSION_SERIALIZER` is set to `PickleSerializer` but the data still has to survive a JSON round-trip in places. Use the helpers `SaveDictionaryOfItemsToSessionStore` / `LoadItemFromSessionStore` in `StatusMonitoredLongRunningProcessPage.py` rather than writing session keys directly; they handle the hex/pickle dance and SQLite-lock retries.

**SQLite lock retry idiom**: every `session.save()` is wrapped in a `while not save_complete` loop that retries 100× at 10Hz before re-raising. When adding new session writes, copy this pattern — concurrent fork children fighting for the SQLite session DB will lock it otherwise.

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
