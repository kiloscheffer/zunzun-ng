# Active gotchas

Operational notes too situational for `AGENTS.md`'s high-level architecture sections. Read the matching section before touching that area. Each bullet captures one rule, one tripping-hazard, or one footgun that has burned someone (or would burn the next person).

## Environment and venv

- `.venv/` must be excluded from cloud-sync clients (Dropbox, OneDrive, iCloud). uv's default hardlink mode on Windows shares inodes between `.venv/` and the global uv cache (`%LOCALAPPDATA%\uv\cache\`); a sync client watching `.venv/` doubles the storage and breaks the hardlink relationship on cross-machine sync, silently corrupting Python imports (manifests as OS error 396 or hard-to-trace `ImportError`s). With the exclusion in place, no special handling is needed (verified 2026-04-28). Workaround if the exclusion isn't possible: prefix `uv` commands with `UV_LINK_MODE=copy`.
- Cold-cache smoke flakiness. The first smoke run after `rm -rf .venv && uv sync` (especially after a pyeq3 reinstall) can time out on 3D scenarios because spawn workers compile `.pyc` files on first import. Re-running on the warm venv passes.
- `rm -rf .venv` may fail with "Device or resource busy" on Windows when transient background processes (Dropbox indexers, Windows Search, etc.) hold handles open momentarily. PowerShell's `Remove-Item .venv -Recurse -Force` uses native Win32 calls and handles these gracefully where bash's `rm -rf` (via MSYS POSIX-emulation) does not.
- Avoid running pytest + smoke in parallel right after a `uv lock` that changed any source URL — they'll race for cache locks.

## Spawn LRP pattern

- Never call `os.getloadavg`, `/proc`, `vmstat`, or `os.popen` directly from view or LRP code. Extend `zunzun/platform_compat.py` instead — it shims the platform-specific calls (Linux uses real loadavg; Windows synthesises one from psutil).
- `os.fork()` and `os._exit()` no longer appear in the codebase. Adding them will break Windows compatibility; prefer `multiprocessing.Process(spawn)` and plain `return` respectively. The `fork-pattern-reviewer` subagent in `.claude/agents/` audits for accidental regressions.
- `get_parallel_process_count()` in `platform_compat.py` is platform-aware: fork platforms use ~80 MB per-worker memory estimate and cap at `cpu_count`; spawn platforms use ~750 MB and hard-cap at 4 workers because each spawned Pool worker re-imports numpy/scipy/pyeq3 from scratch.

## Sessions and state

- Every `session.save()` is wrapped in a `while not save_complete` loop that retries 100× at 10Hz before re-raising. When adding new session writes, copy this pattern — concurrent spawn children fighting for the SQLite session DB will lock it otherwise. Spawn children open fresh DB connections (vs. fork's inherited ones), so lock contention is arguably more relevant post-migration, not less.
- Session values are stored as JSON-native Python types (floats, strings, lists of floats, nested dicts of primitives) via the default `JSONSerializer`. Callers are responsible for casting numpy values to plain Python primitives at write time — see `_json_native` in `StatusMonitoredLongRunningProcessPage.py`.
- Three parallel `SessionStore`s per user — keys stored in the main request session as `session_key_status` / `session_key_data` / `session_key_functionfinder`. The helpers `SaveDictionaryOfItemsToSessionStore` / `LoadItemFromSessionStore` handle routing.

## Templates and URLs

- `/CommonProblems/` is a case-sensitive CapitalCase URL; the on-disk directory is lowercase (`commonproblems/`). The bare trailing-slash URL `/CommonProblems/` is explicitly routed to serve `index.html` because Django's `static()` helper doesn't auto-index.
- The coefficient-picker `<td>` cells in `templates/zunzun/divs/{polyfunctional,polyrational,polynomial_customization}_selection_div.html` have legacy JS dependencies. `id="CPX..."` is read by `JavascriptForFunctionMatrix2D.js` / `JavascriptForFunctionMatrix3D.js` / `JavascriptForRationalMatrix2D.js` / `JavascriptForRationalMatrix3D.js` via `document.all` / `document.layers` pathways; inline `style="background-color:..."` is read via `.style.backgroundColor` to determine selected/unselected state. Do not touch cell `id` or inline `style` without a paired JS rewrite — deferred indefinitely (out of scope for HTML modernization).

## Files and directories

- `static/` (committed assets) and `temp/` (runtime outputs) serve two separate URL prefixes — `STATIC_URL = '/static/'` vs `MEDIA_URL = '/temp/'`. For Python-side paths use `settings.STATIC_FILES_DIR` and `settings.TEMP_FILES_DIR` respectively. They are different paths since the 2026-04-28 static-files restructure; before that, both lived under `temp/`.
- `temp/` is auto-trimmed by `HomePageView`'s housekeeping when total size exceeds `MAX_TEMP_DIR_SIZE_IN_MBYTES` (default 500).
- `pid_trace.py` is dormant by design. Both functions `return` at the top. The calls scattered through `StatusMonitoredLongRunningProcessPage.py` are debugging hooks that are no-ops in production. To enable per-fork trace files, remove the early `return`s; don't remove the call sites.

## Filename grammar in temp/

- Artifact filenames follow `zun_<pid_b36_4>_<ms_b36_8>_<anchor_3>_<rank_2>.{ext}` (per-component) or `zun_<pid_b36_4>_<ms_b36_8>_zun_00.{ext}` (page-level). Helpers live in `zunzun/LongRunningProcess/_unique.py`: `new_unique_string()`, `page_artifact_filename/path/url()`, and the `b36()` formatter.
- Anchor namespace reservations: `zun` is the page-level anchor (PDF, result HTML); `h` prefix is reserved for parametrized histogram instances (`StatisticalDistributionHistogram` uses `h` + 2-char base36 of `distributionIndex`). No other anchor may start with `zun` or `h`.
- `b36()` never truncates: values too large for the requested width produce a longer string. Rank field is sized for 0..1295 (FunctionFinder cap ~1k); larger values produce 3+ char suffixes and break fixed-width sortability for those rows specifically — accepted trade-off.

## FunkLoad legacy

- FunkLoad is not in `pyproject.toml`. Its `setup.py` uses `ez_setup`, which was removed from modern setuptools, so it can't be installed under the uv-managed Python 3.14 environment.
- Its assertion strings in `funkload_tests/test_Simple.py` are also stale under modern numpy/scipy/pyeq3. The folder is preserved as historical reference; do not invest in re-running it. Port individual assertions to pytest or to the smoke script if needed.

## Deploy

- `settings.py` ships with empty placeholders for `SECRET_KEY`, `EXCEPTION_EMAIL_ADDRESS`, `FEEDBACK_EMAIL_ADDRESS`, `EMAIL_HOST_USER`, and `EMAIL_HOST_PASSWORD`. Email sending is gated on these being truthy (see `FeedbackView`, the exception handler in `LongRunningProcessView`), so leaving them blank silently disables email rather than crashing.
- `DEBUG` is toggled automatically by looking for `'runserver'` in `sys.argv` (see `settings.py`), so running under Waitress or WSGI disables debug regardless of env vars.
- Rate limiting is always in effect (no install-time gating). To disable for local testing, set `RATELIMIT_ENABLE = False` in `settings.py`. When a caller exceeds the rate, `CommonToAllViews` applies a 5-second `time.sleep` — this specifically breaks polling endpoints (`StatusUpdateView` is intentionally not decorated with `@ratelimit` for this reason).
