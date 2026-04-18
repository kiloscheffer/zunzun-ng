# Django 2.2 → 5.2 LTS Upgrade — Design

**Date:** 2026-04-18
**Branch (planned):** `django-5-upgrade` in worktree `../zunzunsite3-django5/`
**Status:** Brainstorm complete, awaiting user sign-off before plan.

## 1. Scope & Goals

Upgrade Django from the pinned `>=2.2,<3.0` to `>=5.2,<5.3` (LTS, supported through April 2028). Eliminate all pre-5.x compatibility shims and the ad-hoc `pickle.dumps(...).hex()` session-encoding convention. Replace the unmaintained `django_brake` rate limiter with `django-ratelimit`.

Deliverables:

- Site boots and passes its full test suite under Django 5.2.x on Linux, macOS, and Windows (via Waitress).
- New pytest integration test suite exercises URL resolution, template selection, form handling, session roundtrip, and rate limiting.
- Expanded 9-scenario smoke test (3 existing + 6 new) covers every public route.
- Documentation (`CLAUDE.md`, `.claude/agents/fork-pattern-reviewer.md`, the existing cross-platform spec) updated to match reality.

Non-goals:

- No changes to `pyeq3` / `numpy` / `scipy` / `matplotlib` / `reportlab` versions — they are already on modern releases that were validated during the cross-platform migration.
- No changes to the spawn-based LRP pattern, the three-`SessionStore` split, or the `temp/`-as-static pattern.
- No addition of Django `auth` / `admin` / CSRF middleware.
- No push to `origin` unless the user explicitly requests it after local merge.

## 2. Constraints & Context

- Currently at Django 2.2.28 with a `try/except patterns(...)` shim in `urls.py`, dual `MIDDLEWARE_CLASSES`/`MIDDLEWARE`, dual `TEMPLATE_DIRS`/`TEMPLATES`, `SESSION_SERIALIZER = 'django.contrib.sessions.serializers.PickleSerializer'`, and 6 `render_to_response` call sites in `zunzun/views.py`.
- `django_brake` was last released ~2014 and does not work on modern Django. The current code already falls back to a pass-through decorator when `brake` is not installed.
- The site runs on Python 3.11 via `uv` with deps pinned in `uv.lock`. Django 5.2 requires Python 3.10+ — compatible.
- Session data is currently routed through two helpers in `StatusMonitoredLongRunningProcessPage.py` (`SaveDictionaryOfItemsToSessionStore`, `LoadItemFromSessionStore`) that apply `pickle.dumps(x, pickle.HIGHEST_PROTOCOL).hex()` on write and `pickle.loads(bytes.fromhex(x))` on read. There are also 7 raw pickle/hex sites in `views.py` that bypass the helpers.
- Django 4.1 removed `PickleSerializer` entirely. Keeping pickle would require vendoring it — intentionally not done (security hardening is a feature, not a bug).

## 3. Decisions (Locked In)

| # | Decision | Alternatives considered |
|---|---|---|
| 1 | **Target Django 5.2 LTS** | 4.2 LTS (window ending), stepped 4.2→5.2 migration |
| 2 | **Drop the `pickle.dumps().hex()` convention entirely**; store JSON-native values directly | Vendor `PickleSerializer`; switch to `JSONSerializer` but keep the hex wrapper |
| 3 | **Replace `django_brake` with `django-ratelimit`** | Drop rate limiting; keep the try/except pass-through |
| 4 | **Clean up every pre-5.x compat shim in the same branch** | Minimum-viable (leave duplicates), staged follow-up commit |
| 5 | **Two-layer verification: pytest integration suite + expanded 9-scenario smoke** | pytest only; smoke only; status quo |
| 6 | **Single worktree with ordered-phase commits** | Series of small branches |

## 4. Components Touched

### 4.1 `pyproject.toml`
- `django>=2.2,<3.0` → `django>=5.2,<5.3`.
- Add `django-ratelimit` to runtime deps.
- Leave `beautifulsoup4` and `lxml` as-is (both still used by `CreateReportPDF`).

### 4.2 `urls.py`
- Delete the entire `try: patterns(...) except: [url(...)]` block.
- Replace with a single list of `re_path(regex, view_fn)` entries using `from django.urls import re_path`.
- Function-based views continue to work as callables — no `.as_view()` needed because no class-based views are in use.

### 4.3 `settings.py`
- Drop `MIDDLEWARE_CLASSES` (keep only `MIDDLEWARE`).
- Drop `TEMPLATE_DIRS`, `TEMPLATE_LOADERS`, `TEMPLATE_DEBUG` (keep only the `TEMPLATES = [...]` list).
- Drop `SESSION_SERIALIZER = 'django.contrib.sessions.serializers.PickleSerializer'` — Django 5 defaults to `JSONSerializer`.
- Keep the `DEBUG = 'runserver' in sys.argv` heuristic unchanged.
- Keep `SITE_ID`, `ALLOWED_HOSTS`, `TIME_ZONE`, `SECRET_KEY` placeholder, `STATIC_URL = '/temp/'`, `STATICFILES_DIRS` unchanged.

### 4.4 `zunzun/views.py`
- Replace `from django.shortcuts import render_to_response` with `from django.shortcuts import render`.
- Rewrite all 6 `render_to_response(template, ctx)` → `render(request, template, ctx)`. All call sites already have `request` in scope.
- Replace the `django_brake` try/except import block with `from django_ratelimit.decorators import ratelimit`.
- Update 5 `@ratelimit(rate='12/m')` decorators to the new-API signature `@ratelimit(key='ip', rate='12/m', block=False)`. `request.limited` continues to be set; the `time.sleep(5)` branch in `CommonToAllViews` keeps working.
- Rewrite all 7 raw `pickle.dumps(...).hex()` / `pickle.loads(bytes.fromhex(...))` sites (the `time_of_last_status_check`, `currentStatus`, `start_time`, `timestamp`, `redirectToResultsFileOrURL` reads/writes) to store/read native Python values directly.

### 4.5 `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py`
- `SaveDictionaryOfItemsToSessionStore` — remove `pickle.dumps(item, pickle.HIGHEST_PROTOCOL).hex()`; write the raw value. Preserve the 100-retry-at-10-Hz SQLite lock loop verbatim.
- `LoadItemFromSessionStore` — remove `pickle.loads(bytes.fromhex(returnItem))`; return the value as stored. Preserve the `None` default when the key is absent.
- Contract change (documented): callers are responsible for producing JSON-native values (no numpy scalars, no `datetime`, no sets).

### 4.6 `zunzun/LongRunningProcess/FunctionFinder.py` and `FunctionFinderResults.py`
- Cast ranking tuples to JSON-native types at the write site before calling `SaveDictionaryOfItemsToSessionStore`. Specifically: `float(...)` on any numpy scalar, `.tolist()` on any numpy array inside the ranking payload.
- This isolates the "numpy escapes into session" risk to one place rather than spreading JSON-safety logic through the session helpers.

### 4.7 Templates (`zunzun/templates/`)
- Audit for deprecated template tags (`{% ifequal %}`, `{% ifnotequal %}`, `{% ssi %}` are all long gone). Expected to be clean — the templates are simple and haven't been touched in years — but verify via Django 5's `manage.py check`.

### 4.8 `tests/` — new pytest integration suite

```
tests/
  conftest.py                   # pytest-django fixtures, Client with pre-seeded session
  test_urls.py                  # all 10 routes resolve to the correct view
  test_views_render.py          # HomePage / AllEquations / Feedback / InvalidForm → 200 + correct template
  test_views_dispatch.py        # LongRunningProcessView spawn dispatch with multiprocessing.Process mocked
  test_session_roundtrip.py     # Save/LoadItemFromSessionStore with JSON-native values end-to-end
  test_ratelimit.py             # 13 rapid POSTs → 13th hits request.limited branch
  test_evaluate_at_a_point.py   # seed session_data dict, POST /EvaluateAtAPoint/, assert numeric response
```

Design points:

- Tests must not spawn real children (slow, OS-coupled). `multiprocessing.Process.start` is patched in `conftest.py` to a no-op that records the invocation.
- Tests must not render matplotlib or PDF. Those paths are stubbed at the LRP boundary.
- Session roundtrip test uses values deliberately exercising the edge cases: Python floats, lists of floats, nested dicts, strings with non-ASCII characters.

### 4.9 Smoke test expansion (`scripts/smoke_test.py`)

6 new scenarios — final suite is 9 scenarios:

| # | Scenario | Route | Asserts |
|---|---|---|---|
| 1 | `polynomial_quadratic_2D` (existing) | POST `/FitEquation__F__/2/Polynomial/2nd Order (Quadratic)/` | coeff/stats markers |
| 2 | `function_finder_2D` (existing) | POST `/FunctionFinder__F__/2/` | ranking markers |
| 3 | `function_finder_detail_2D` (existing) | POST on RANK=1 link | coeff/stats markers |
| 4 | `characterize_2D` | POST `/CharacterizeData/2/` | statistics page markers |
| 5 | `polynomial_quadratic_3D` | POST `/FitEquation__F__/3/Polynomial/Full Quadratic/` | coeff/stats markers for 3D |
| 6 | `all_equations_2D` | GET `/AllEquations/2/Polynomial/` | listing-page markers |
| 7 | `feedback_form` | GET `/Feedback/` then POST with sample fields | reply template marker |
| 8 | `evaluate_at_a_point` | Chained after scenario 1; POST `/EvaluateAtAPoint/` with X value | numeric Y marker in response body |
| 9 | `invalid_form_post` | POST `/FitEquation__F__/2/Polynomial/2nd Order (Quadratic)/` with malformed `textDataEditor` (non-numeric) | `invalid_form_data.html` marker |

Added smoke runtime: ~2–3 min on Linux, ~3–5 min on Windows.

### 4.10 Documentation
- `CLAUDE.md` — rewrite the "Django version pin" paragraph (Django is now 5.2.x, no cross-version shims); rewrite the PickleSerializer paragraph (now JSONSerializer, helpers store native values); update rate-limiting paragraph (`django-ratelimit`, not `django_brake`).
- `.claude/agents/fork-pattern-reviewer.md` — remove/rewrite the "Session data is pickle-hex encoded" bullet and the canonical snippet; replace with "callers write JSON-native values through the helpers."
- `docs/superpowers/specs/2026-04-17-cross-platform-design.md` — add a note to §11 (Non-goals) that the Django 5.2 migration has since been completed; keep the §12 Lessons Learned as-is.

## 5. Session Serializer Rewrite — Key-by-Key Contract

| Session store | Key | Previous wire format | New wire format |
|---|---|---|---|
| status | `timestamp` | hex(pickle(float)) | float |
| status | `start_time` | hex(pickle(float)) | float |
| status | `time_of_last_status_check` | hex(pickle(float)) | float |
| status | `currentStatus` | hex(pickle(str \| dict)) | str or dict of primitives |
| status | `redirectToResultsFileOrURL` | hex(pickle(str)) | str |
| data | `inEquationName`, `inEquationFamilyName` | hex(pickle(str)) | str |
| data | coefficient list | hex(pickle(list-of-numpy-floats)) | list[float] (cast at write site) |
| functionfinder | `functionFinderResultsList` | hex(pickle(list-of-ranking-tuples with numpy)) | list[list[...]] (cast at write site) |

The roundtrip test in `tests/test_session_roundtrip.py` covers each of these shapes with representative data.

## 6. Execution Phases

1. **Phase 0 — Setup.** Create worktree `../zunzunsite3-django5/`, branch `django-5-upgrade` off `master`. Confirm existing 46 unit tests + 3 smoke scenarios pass at HEAD before touching anything.
2. **Phase 1 — Smoke expansion (on current Django 2.2).** Add the 6 new smoke scenarios against the current codebase. Get them all green on Windows. Commit. *Rationale: the new scenarios serve as a safety net for the upgrade, not just a smoke test of it.*
3. **Phase 2 — Pytest integration suite (on current Django 2.2).** Build `tests/test_urls.py`, `test_views_render.py`, `test_views_dispatch.py`, `test_session_roundtrip.py`, `test_ratelimit.py`, `test_evaluate_at_a_point.py`. Get all green. Commit.
4. **Phase 3 — Session serializer refactor.** Drop the pickle/hex dance in both helpers and all 7 raw `views.py` sites. Add JSON-native casts at the `FunctionFinder` / `FunctionFinderResults` write sites. Drop `SESSION_SERIALIZER` from `settings.py`. Tests + smoke pass. Commit. *Still Django 2.2.*
5. **Phase 4 — `django_brake` → `django-ratelimit`.** Swap the import; update the 5 decorator signatures; verify the rate-limit pytest test passes. Commit. *Still Django 2.2.*
6. **Phase 5 — Django 5.2 version bump.** Update `pyproject.toml` pin. `uv sync`. In one atomic commit: `render_to_response` → `render` across the 6 views, `url()` / `patterns()` → `re_path` in `urls.py`, settings.py shim cleanup (`MIDDLEWARE_CLASSES`, `TEMPLATE_DIRS`, `TEMPLATE_LOADERS`, `TEMPLATE_DEBUG`). `manage.py check` clean. Commit.
7. **Phase 6 — Template audit + final run.** `manage.py check`; scan templates for deprecated tags. Run full 9-scenario smoke + full pytest suite on Windows. Commit any fixes.
8. **Phase 7 — Documentation updates.** `CLAUDE.md`, `.claude/agents/fork-pattern-reviewer.md`, cross-platform spec non-goal note. Commit.
9. **Phase 8 — Merge to local master.** `git merge --no-ff django-5-upgrade` on `master` from inside the main checkout. Do NOT push to `origin` unless explicitly asked.

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| `PickleSerializer` bypass: some session read/write outside the helpers. | Phase 3 grep for `session[...]` assignments in all of `zunzun/`; covers the 7 known sites in `views.py`. |
| numpy types leaking into JSON-backed session. | Explicit cast at write sites (§5 table). `test_session_roundtrip.py` asserts `json.dumps(value)` succeeds on every stored value. |
| `django-ratelimit` decorator signature differs from `django_brake`. | `test_ratelimit.py` hits the rate limit deterministically and asserts `request.limited`; catches signature/API drift. |
| Deprecated template tag in `zunzun/templates/`. | Template parsing happens on render, not at boot. 9-scenario smoke renders every template on every public route; any `TemplateSyntaxError` surfaces as a scenario failure. Phase 6 also does a grep for known-removed tags (`{% ifequal %}`, `{% ifnotequal %}`, `{% ssi %}`). |
| `STATIC_URL` / `STATICFILES_DIRS` semantics changed in 5.x. | `/temp/` + filesystem source dir is still supported in 5.2; smoke test scenario 1 already embeds graphs from `/temp/`. |
| `request.session` API changed or session keys no longer string-safe. | Phase 3 end-to-end pytest roundtrip confirms. |
| Windows-only regression. | Phase 6 full run on Windows (primary dev environment); pattern already validated during cross-platform migration. |
| `multiprocessing.Process(spawn)` interaction with Django 5 startup changed. | Covered by existing `tests/test_child_payload.py` and the smoke test. If `django.setup()` in `child_payload.py` breaks on 5.2, surfaces immediately in Phase 5. |
| `STATICFILES_STORAGE` deprecated in Django 5 in favor of `STORAGES = {...}`. | Not currently set — defaults are used. Default still works in 5.2 (compat shim removed in 6.0). No action needed; flag for a future Django 6.0 upgrade. |

## 8. Acceptance Criteria

- `uv run python manage.py check` reports no errors.
- `uv run pytest tests/ -v` shows 46 existing tests + N new integration tests, all pass.
- `uv run python scripts/smoke_test.py` shows `SMOKE OK: all scenarios passed` for all 9 scenarios on Windows.
- `grep -r "render_to_response\|MIDDLEWARE_CLASSES\|TEMPLATE_DIRS\|TEMPLATE_LOADERS\|TEMPLATE_DEBUG\|PickleSerializer\|pickle\.dumps.*\.hex\|pickle\.loads.*fromhex\|django_brake\|from brake" .` returns only matches inside `docs/` (historical/spec references) and `uv.lock`.
- `urls.py` no longer imports from `django.conf.urls` (old compat module) and no longer contains the word `patterns` or a bare `url(` call.
- `pyproject.toml` shows `django>=5.2,<5.3` and `django-ratelimit` in runtime deps.
- `CLAUDE.md` reflects the new state (no "Django pinned pre-3.0" language).
- Site runs under `uv run python manage.py runserver` and under `uv run waitress-serve --listen=127.0.0.1:8000 wsgi:application`.
