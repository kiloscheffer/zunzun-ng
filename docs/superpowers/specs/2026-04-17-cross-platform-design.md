# Cross-platform migration — design

**Date:** 2026-04-17
**Status:** Design approved, ready for implementation plan
**Author:** Kilo Scheffer + Claude (brainstorming session)

## 1. Context

ZunZunSite3 is today a Linux-only Django site. The README explicitly states: *"the code uses Unix-style process forking, and this is not available on the Windows operating system."* Beyond fork, the codebase has accumulated a set of POSIX-specific dependencies:

| Call site | File (line) | Portability concern |
|---|---|---|
| `os.fork()` | `zunzun/views.py` (417, 494) | Not available on Windows Python |
| `os.nice(level)` | `zunzun/views.py` (420) | Not available on Windows |
| `os._exit(0)` × 5 | `views.py` (447, 530), `StatusMonitoredLongRunningProcessPage.py` (672, 689), `FitUserDefinedFunction.py` (67) | Unix-fork idiom |
| `os.getloadavg()` × 3 | `views.py` (216, 543), `StatusMonitored…` (822) | Linux/macOS only on older Python |
| `open('/proc/loadavg')` | `StatusMonitoredLongRunningProcessPage.py` (184) | Linux-only |
| `os.popen('vmstat')` | `StatusMonitoredLongRunningProcessPage.py` (169) | Linux-only, requires `vmstat` binary |
| `psutil.STATUS_ZOMBIE` reap | `views.py` (680) | Zombies only exist on Unix |
| `os.popen('mogrify …')` × 2 | `ReportsAndGraphs.py` (1513, 1575) | Cross-platform binary, but `os.popen` shell injection risk |
| `os.popen('gifsicle …')` × 2 | `ReportsAndGraphs.py` (1517, 1579) | Cross-platform binary, same shell risk |
| `os.popen('rm …')` × 2 | `ReportsAndGraphs.py` (1519, 1581) | POSIX-only command |

The architectural heart of the Linux dependency is the **fork-and-redirect pattern** documented in `CLAUDE.md > "The fork-based long-running-process pattern"`: a POST lands in `LongRunningProcessView`, which picks an `LRP` subclass, `os.fork()`s, the parent returns `HttpResponseRedirect('/StatusAndResults/')`, and the child runs `PerformAllWork()` while writing progress to a shared SQLite SessionStore.

## 2. Goals & scope

**Goal:** ZunZunSite3 runs natively (without WSL or Docker escape hatches) on Linux, macOS, and Windows for both development and production use. Each platform has a documented, tested-or-templated deployment recipe.

**Non-goals:**

- Not tackled in this work: the Django 2.x → 4.2 LTS migration (`render_to_response`, `url()`, `PickleSerializer`). The existing `django<3.0` pin stays; the `try/except patterns` shim in `urls.py` and the `MIDDLEWARE_CLASSES = MIDDLEWARE` alias in `settings.py` remain untouched.
- Not tackled: FunkLoad replacement or porting. FunkLoad is already broken on modern setuptools; the smoke test in this spec partially substitutes for its value but is not a full replacement.
- Not tackled: CI matrix automation (see Section 7).
- Not tackled: Docker packaging. Docker already solves cross-platform by running Linux containers; out of scope here.

## 3. Approach

Three approaches were considered:

| Approach | Summary | Why rejected / chosen |
|---|---|---|
| **(1) `multiprocessing.Process` (spawn)** | Replace `os.fork()` with a spawn-based Process | **Chosen.** Preserves process isolation (a pyeq3/scipy C-level crash kills the child, not the web server). Spawn is the only option on Windows, the default on modern macOS, and the safe choice under a multi-threaded server like Waitress on Linux. |
| **(2) `threading.Thread`** | Run fits in background threads within the web process | Rejected. Simpler migration, but loses process isolation. A scipy segfault would take down the web server. |
| **(3) External task queue (RQ/Huey)** | Extract fits into a separate worker process with Redis or SQLite broker | Rejected *for now*. Cleanest production architecture, but adds infrastructure dependencies and is over-engineering for current traffic. Worth revisiting if site usage grows. |

## 4. Architecture

### 4.1 Fork replacement

Both `os.fork()` call sites become `multiprocessing.Process` with the `spawn` start method:

```python
ctx = multiprocessing.get_context("spawn")
child = ctx.Process(target=_run_fit_child, args=(child_payload,), daemon=False)
child.start()
```

`spawn` is mandated over `fork`/`forkserver` because:

- **Windows:** `fork` does not exist; `spawn` is the only option.
- **Linux + multi-threaded server (Waitress):** `fork` inside a multi-threaded process inherits all threads' lock states and can deadlock on Python's own locks. `spawn` avoids this class of bug by starting a fresh interpreter.
- **macOS:** `spawn` is the default on Python 3.8+ for exactly the above reason.

Forcing `spawn` on all platforms is a deliberate behavior change from today's fork pattern. It costs ~300–1000 ms per child start (re-importing Python) — invisible compared to the seconds-to-minutes typical fit runtime.

### 4.2 Picklability and `ChildPayload`

`spawn` pickles the target function and its arguments to hand them to the child. The current `LRP` instance at the moment of fork holds:

- Primitives, session keys, `dataObject` — picklable.
- `self.boundForm` (a Django Form bound to the WSGI request) — **not safely picklable** across `spawn`.
- `self.boundForm.equation` (a pyeq3 equation) — picklable (the existing in-process `multiprocessing.Pool` in `FunctionFinder.py` already relies on this).

The resolution is to introduce a small **`ChildPayload`** dataclass carrying only what `PerformAllWork()` actually needs, built in the parent immediately before the Process is started:

```python
@dataclass
class ChildPayload:
    lrp_class_name: str           # reconstruct the LRP subclass in the child
    session_key_status: str
    session_key_data: str
    session_key_functionfinder: str
    dimensionality: int
    renice_level: int
    data_object: DataObject       # existing class; already picklable
    equation: Any                 # pyeq3 equation (verified via spike)
    extra: dict[str, Any]         # subclass-specific primitives
```

Each LRP subclass implements `build_child_payload(self) -> ChildPayload`. Default lives on `StatusMonitoredLongRunningProcessPage`; `FittingBaseClass` overrides to include fit-specific fields; each concrete `Fit{Spline,UserDefinedFunction,UserSelectable*,UserCustomizable*}` subclass extends `extra` with its specific flags.

### 4.3 Knock-on changes

- **`os._exit(0)` → plain `return`.** `multiprocessing` handles child cleanup correctly across platforms.
- **`os.nice(level)` → `psutil.Process().nice(level)`.** psutil handles the Windows priority-class mapping internally; no translation required in our code.
- **Zombie-reap loop → `multiprocessing.active_children()` sweep.** No-op on Windows (no zombies exist there), correct cleanup on Unix.

### 4.4 Empirical risk to verify in Phase 2

The only significant unknown is whether pyeq3 equation instances pickle cleanly across a `spawn` boundary. In-process `Pool.map()` pickles are a strong signal they will, but `spawn` is stricter (the full module import graph must be importable from a fresh interpreter). **Verification:** a small `test_spawn_roundtrip.py` test in Phase 0 that exercises pickle round-trip on one instance of each concrete Fit* class, before rewiring any production call sites.

## 5. Platform abstraction module

### 5.1 New file: `zunzun/platform_compat.py`

Single-file module consolidating all platform-specific behavior. Named `platform_compat` (not `platform`) to avoid shadowing Python's stdlib `platform` module.

### 5.2 Public surface

```python
# zunzun/platform_compat.py

def get_loadavg() -> tuple[float, float, float]: ...
#   Unix: os.getloadavg(). Windows: psutil.getloadavg(). Returns (0, 0, 0)
#   with one-time warning if unavailable.

def get_parallel_process_count(cpu_cap: int | None = None) -> int: ...
#   Replaces StatusMonitoredLongRunningProcessPage.GetParallelProcessCount().
#   Same throttling logic driven by psutil.virtual_memory() + psutil.getloadavg()
#   instead of parsing `vmstat` stdout and reading /proc/loadavg.

def set_process_niceness(pid: int, niceness: int) -> None: ...
#   Wraps psutil.Process(pid).nice(niceness). psutil handles the Windows
#   priority-class translation.

def reap_completed_children() -> None: ...
#   Replaces the psutil.STATUS_ZOMBIE loop. Uses multiprocessing.active_children()
#   + join(timeout=0). Safe on all platforms.

def run_tool(binary: str, args: list[str], stdout_file: Path | None = None) -> int: ...
#   Typed subprocess wrapper replacing os.popen() shellouts. No shell=True.
#   Side-benefit: removes pre-existing shell-injection surface.

def remove_files_matching(pattern: str) -> int: ...
#   glob.glob + os.remove, replaces os.popen('rm path__*').

def ensure_external_binaries() -> list[str]: ...
#   Uses shutil.which() to check for mogrify and gifsicle.
#   Called once from zunzun/apps.py AppConfig.ready().
#   Returns list of missing binary names.
```

### 5.3 Design choices

- **No classes, no abstract base.** psutil already handles the cross-platform heavy lifting; `platform_compat` is a thin consolidation layer, not an abstraction hierarchy.
- **Generic `run_tool(binary, args, …)` rather than one function per external tool.** Two tools currently (`mogrify`, `gifsicle`), six call sites — uniform is better than bespoke.

## 6. Component-by-component changes

### 6.1 File-by-file impact

| File | Changes | Rough effort |
|---|---|---|
| `zunzun/platform_compat.py` | **New** — abstraction module from Section 5 | 1–2 hours |
| `zunzun/LongRunningProcess/child_payload.py` | **New** — `ChildPayload` dataclass + `_run_fit_child` entrypoint | 1 hour |
| `zunzun/apps.py` | **New** — `AppConfig.ready()` calls `ensure_external_binaries()` | 30 minutes |
| `zunzun/__init__.py` | Add `default_app_config = 'zunzun.apps.ZunZunConfig'` (or update `INSTALLED_APPS`) | 5 minutes |
| `zunzun/views.py` | `LongRunningProcessView` fork → Process(spawn); `HomePageView` housekeeping fork → Process(spawn); load-avg calls → `platform_compat.get_loadavg()`; zombie loop → `platform_compat.reap_completed_children()` | 3–4 hours |
| `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py` | `GetParallelProcessCount()` → wrapper around `platform_compat`; 2× `os._exit(0)` → return; add default `build_child_payload()` | 2 hours |
| `zunzun/LongRunningProcess/FittingBaseClass.py` | Override `build_child_payload()` for fit-specific fields | 1 hour |
| `zunzun/LongRunningProcess/Fit{Spline,UserDefinedFunction,UserSelectable*,UserCustomizable*}.py` | Each overrides `build_child_payload()` to populate its `extra` entries; `os._exit(0)` in `FitUserDefinedFunction` → return | 2–3 hours total |
| `zunzun/LongRunningProcess/ReportsAndGraphs.py` | 4× `os.popen('mogrify/gifsicle …')` → `run_tool`; 2× `os.popen('rm …')` → `remove_files_matching` | 1 hour |
| `pyproject.toml` | Add `waitress` to the default dependency group | 1 minute |
| `wsgi.py` | Verified to import cleanly under `waitress-serve`; no code change expected | 0 |

**Rough total:** ~2 working days of code + 1 day of cross-platform verification.

### 6.2 Tricky cases

1. **`FitUserDefinedFunction` inner fork.** The class does its own inner fork (line 67) to isolate compilation of user-supplied Python (defense against infinite loops). This also migrates to `multiprocessing.Process(spawn)` — same pattern as the outer fork.
2. **Session DB retry loop preserved as-is.** SQLite locking under concurrent child-process writes is *more* relevant with spawn (child has freshly-opened DB connections), not less. The existing 100-retry-at-10-Hz loop in `SaveDictionaryOfItemsToSessionStore` is a keeper.
3. **`gifsicle` shell redirection.** Current code uses `os.popen('gifsicle … > outfile')`. New code uses `run_tool('gifsicle', [...], stdout_file=outfile)` — functionally equivalent, slightly different buffering semantics (Python-buffered rather than shell-buffered).

### 6.3 Explicitly out of scope

- Django 2.x → 4.2 LTS migration (separate branch)
- The `urls.py` `patterns()` try/except shim (vestigial but harmless; lives or dies with the Django upgrade)
- The `MIDDLEWARE_CLASSES = MIDDLEWARE` alias in `settings.py` (same)
- FunkLoad replacement (partial substitution via smoke test; full replacement deferred)
- New features, refactors beyond what's needed for portability

## 7. Testing strategy

### 7.1 Unit tests — `platform_compat`

Each function gets a simple test:

- `get_loadavg()` returns 3-tuple of floats; mock `psutil.getloadavg` for the "unavailable" path.
- `get_parallel_process_count(cpu_cap=4)` returns an int in `[1, min(cpu_cap, cpu_count)]`; `get_parallel_process_count()` with no cap returns in `[1, cpu_count]`.
- `remove_files_matching('/tmp/nonexistent__*')` returns 0 cleanly.
- `run_tool('nonexistent-binary', [])` raises `FileNotFoundError` (not a silent hang).

### 7.2 Pickle round-trip test for `ChildPayload`

One test per concrete LRP subclass: instantiate a representative fit, call `build_child_payload()`, `pickle.dumps` / `pickle.loads` round-trip, assert all fields intact. This is the empirical verification of the picklability assumption from §4.2 — runs before any production call site is rewired.

### 7.3 Cross-platform smoke script — `scripts/smoke_test.py`

New, ~150 lines. Starts Waitress as a subprocess, uses `requests` to POST a 2D polynomial-quadratic fit against the test data in `funkload_tests/test_Simple.py`, polls `/StatusAndResults/` until completion, asserts on known numeric coefficients, kills Waitress. Runnable via `uv run python scripts/smoke_test.py` on any OS.

The existing FunkLoad assertion strings (e.g., `'5.084392E+00'`, `'RMSE: 0.2870'`) are preserved as reference data in the smoke script's docstring — the numeric expectations survive even though FunkLoad itself does not.

### 7.4 CI — deliberately out of scope

GitHub Actions 3-OS matrix was considered and deferred. Rationale: the project origin is currently Bitbucket; moving to GitHub Actions would add repo-mirroring complexity that outweighs the value of automated matrix runs at the project's current scale. Local smoke-testing via `scripts/smoke_test.py` on each platform before release substitutes acceptably.

If CI becomes desirable later, the smoke script is already written and portable; adding `.github/workflows/ci.yml` is a one-file follow-up.

## 8. Production deployment recipes

### 8.1 Documentation structure

```
docs/
  deployment/
    README.md      # 2-paragraph overview, links to per-platform docs
    linux.md       # canonical recipe; Ubuntu 22.04/24.04 focus
    macos.md       # Homebrew-based, launchd supervisor
    windows.md     # IIS + Waitress + NSSM, longest of the three
```

`README.txt` (project root) gains a one-paragraph "Production deployment: see `docs/deployment/`" pointer.

### 8.2 Linux recipe (`docs/deployment/linux.md`)

Documents two stacks, recommending the first:

- **Stack A (recommended): nginx → Waitress.** Uniform command across all platforms. systemd unit template included.
- **Stack B: nginx → gunicorn sync workers.** Preserves existing deployments. **Critical config constraint:** `--worker-class sync --threads 1`, because gunicorn's `gthread` multi-threaded worker reintroduces the fork-safety hazard that §4.1 eliminated. Apache + mod_wsgi gets a mention as "also works with the same `threads=1` constraint."

### 8.3 macOS recipe (`docs/deployment/macos.md`)

Structurally identical to Linux; deltas documented:

- `brew install imagemagick gifsicle` (vs apt-get)
- **launchd** plist (vs systemd unit)
- nginx via Homebrew

Explicitly annotated: **the launchd plist is not verified on a live macOS machine** during this migration (Section 9). The user or a contributor running macOS is the canonical verifier.

### 8.4 Windows recipe (`docs/deployment/windows.md`)

Five phases:

1. **System prerequisites:** Python 3.11 (or via `uv python install 3.11`); `winget install ImageMagick.ImageMagick` and `gifsicle` (or manual); PATH verification.
2. **Site layout:** recommended disk location, permissions for the IIS Application Pool identity (read on code, write on `temp/` and `session_db/`), `uv sync --no-dev` run as the service account.
3. **Waitress as a Windows Service via NSSM:** install NSSM, configure service pointing at `.venv\Scripts\waitress-serve.exe`, verify via curl.
4. **IIS reverse proxy:** install IIS Web Server role + URL Rewrite 2.1 + Application Request Routing 3.0; enable proxy in IIS Manager; URL Rewrite rule forwards all traffic to `127.0.0.1:8000`; static files (`temp/static_images/`) served directly by IIS.
5. **Operational notes:** log locations (NSSM captures stdout/stderr), process-restart command (`nssm restart`), expected `python.exe` child-process count in Task Manager, Windows Defender exclusion recommendation for `.venv/` to avoid fit latency spikes.

### 8.5 Docker

Out of scope. One-sentence stance in `docs/deployment/README.md`: *"If you're Docker-native, pick a `python:3.11-slim` base image and follow the Linux recipe inside the container — Docker itself handles cross-platform."*

### 8.6 Static files and logging (cross-cutting)

- Static files in `temp/static_images/` served via `STATIC_URL = '/temp/'`; in production the reverse proxy (nginx/IIS) serves them directly, bypassing Waitress. Configuration-only, no code change.
- Logging via `logging.basicConfig` to `temp/{pid}.log` on top-level child exceptions; no rotation. Each platform recipe suggests a cron/Scheduled Task for log cleanup (partially handled already by `HomePageView` housekeeping temp-dir trim).

## 9. Migration phasing

Each phase is one commit or a small series; each phase leaves Linux production operational.

| Phase | Scope | Linux impact | Windows impact |
|---|---|---|---|
| **0** | Add `platform_compat.py` (pure addition); pickle round-trip tests for each LRP subclass | None | None |
| **1** | Migrate `os.getloadavg`, `/proc`, `vmstat`, `os.popen` sites → `platform_compat`. Still uses `os.fork()`. | Identical behavior (psutil delegates to same kernel interfaces) | Still fails at first fork, but 80% closer |
| **2** | **Risky.** `ChildPayload` + spawn replaces `os.fork()` in `LongRunningProcessView`. Updated call sites: `os._exit` removals, `build_child_payload()` overrides | Behavior shift: child startup ~300–1000 ms slower. Verify via smoke test | First phase where a fit actually completes on Windows |
| **3** | `HomePageView` housekeeping fork + `FitUserDefinedFunction` inner fork → spawn | Minor | Homepage loads without error |
| **4** | `waitress` added to default deps; `zunzun/apps.py` with `ready()` hook for binary availability. Verified `waitress-serve` serves the site on Linux + Windows | New server option; existing gunicorn/mod_wsgi still work | Primary production server choice |
| **5** | `docs/deployment/{linux,macos,windows}.md` + systemd unit, launchd plist, IIS/NSSM walkthrough | New docs | New docs; also drives verification |

**Risky phase is Phase 2.** Everything else is either additive, mechanical, small-delta, or documentation. Phase 2 is where semantics genuinely change — spawn start method, pickle barrier, ChildPayload boundaries.

## 10. Definition of done

Cross-platform migration is complete when all are true:

1. `uv sync && uv run python manage.py check && uv run python manage.py migrate` succeeds on Ubuntu, macOS, and Windows native Python 3.11.
2. `scripts/smoke_test.py` exits 0 on all three OSes, completing a 2D polynomial-quadratic fit end-to-end.
3. `docs/deployment/{linux.md,macos.md,windows.md}` exist, each with at least one tested-or-templated config.
4. `platform_compat.ensure_external_binaries()` correctly reports missing `mogrify`/`gifsicle` on a fresh install and does not raise when they're present.
5. `README.txt` no longer contains *"the code uses Unix-style process forking, and this is not available on the Windows operating system."*

## 11. Risks & open questions

- **Pickle-across-spawn for pyeq3 equations.** Strong prior signal (existing Pool pickles them), but must be verified empirically in Phase 0 before committing Phase 2.
- **macOS deployment recipe is unverified.** No macOS hardware in the migration author's environment; `launchd` plist is written by structural extension from the Linux systemd unit. Explicit caveat in `docs/deployment/macos.md`.
- **Windows Defender interaction.** Anecdotally slows fits substantially when scanning `.venv/`. Mitigation is documented (exclusion recommendation) but not forced.
- **Session DB contention under spawn.** Spawn children open fresh DB connections; concurrent writes may contend more than under fork. Existing 100-retry loop should absorb this, but smoke test under simulated concurrency is prudent.
- **`FitUserDefinedFunction` inner fork** compiling user-supplied Python in an isolated child: the isolation property must survive the spawn migration (it does — `multiprocessing.Process(spawn)` provides the same isolation as fork plus a fresh interpreter).

## 12. Follow-ups (out of scope for this spec)

- GitHub Actions 3-OS CI matrix (if repo moves to or mirrors on GitHub).
- Django 2.x → 4.2 LTS migration — separate branch, separate spec.
- FunkLoad replacement with pytest + requests (substantially richer than `scripts/smoke_test.py`).
- Consideration of Approach 3 (external task queue via RQ or Huey) if site traffic grows.

---

**Next step:** invoke `writing-plans` skill to produce the implementation plan.
