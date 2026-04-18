# Windows deployment

Tested on Windows 11 Pro with IIS 10 during the April 2026 cross-platform migration. The `scripts/smoke_test.py` end-to-end test passes on this stack.

## Architecture

```
Internet
   │
   ▼
  IIS (port 80/443, TLS termination, static files)
   │  [URL Rewrite + ARR reverse-proxy rule]
   ▼
  Waitress on 127.0.0.1:8000 (NSSM-managed Windows Service)
   │
   ▼
  spawned fit children (multiprocessing.Process, one per POST)
   │
   ▼
  SQLite session DB (session_db/db.sqlite3)
```

## Phase 1 — System prerequisites

### Python via uv

```powershell
winget install --id=astral-sh.uv
uv python install 3.11
```

### mogrify (ImageMagick) and gifsicle

```powershell
winget install ImageMagick.ImageMagick
# gifsicle: if the winget package is unavailable, download gifsicle.exe from
# https://eternallybored.org/misc/gifsicle/ and add its directory to PATH.
```

Verify both are discoverable:

```powershell
where.exe magick
where.exe gifsicle
```

If either `where.exe` returns nothing, fix `PATH` via System Properties → Environment Variables before continuing. The site's `AppConfig.ready()` logs a prominent warning at startup for any missing binary, but fits-without-animation still work; only animated GIF output fails.

## Phase 2 — Site layout

Choose a path outside `C:\inetpub` (IIS doesn't need to host the code — it proxies to Waitress):

```powershell
mkdir C:\sites\zunzunsite3
cd C:\sites\zunzunsite3
git clone https://bitbucket.org/zunzuncode/zunzunsite3.git .
uv sync --no-dev
uv run python manage.py migrate
```

Grant the IIS Application Pool identity (commonly `IIS APPPOOL\zunzunsite3`) or the NSSM service account read-on-code and write-on-temp/session_db:

```powershell
icacls C:\sites\zunzunsite3\temp /grant "IIS APPPOOL\zunzunsite3:(OI)(CI)M"
icacls C:\sites\zunzunsite3\session_db /grant "IIS APPPOOL\zunzunsite3:(OI)(CI)M"
```

Adjust the identity string to match your configuration. For NSSM-managed Waitress (Phase 3), the service's `LocalService` or a dedicated service account needs the same ACLs.

## Phase 3 — Waitress as a Windows Service via NSSM

Download NSSM from https://nssm.cc/ and place `nssm.exe` in a known location (e.g. `C:\Tools\nssm\`).

Install the service (elevated PowerShell):

```powershell
C:\Tools\nssm\nssm.exe install zunzunsite3 `
    "C:\sites\zunzunsite3\.venv\Scripts\waitress-serve.exe" `
    "--listen=127.0.0.1:8000" "wsgi:application"
nssm set zunzunsite3 AppDirectory C:\sites\zunzunsite3
nssm set zunzunsite3 AppStdout C:\sites\zunzunsite3\waitress.log
nssm set zunzunsite3 AppStderr C:\sites\zunzunsite3\waitress.err
nssm set zunzunsite3 Start SERVICE_AUTO_START
nssm start zunzunsite3
```

Verify Waitress responds directly (before IIS):

```powershell
curl.exe http://127.0.0.1:8000/
```

Should return the homepage HTML (~30 KB).

## Phase 4 — IIS reverse proxy

### Install required IIS components

Elevated PowerShell:

```powershell
Install-WindowsFeature -Name Web-Server, Web-Mgmt-Console
```

Then download and install (GUI):

- **URL Rewrite 2.1** — https://www.iis.net/downloads/microsoft/url-rewrite
- **Application Request Routing 3.0 (ARR)** — https://www.iis.net/downloads/microsoft/application-request-routing

### Enable proxy in ARR

IIS Manager → (server node) → **Application Request Routing Cache** → (right panel) **Server Proxy Settings** → check **Enable proxy** → Apply.

### Create IIS site

1. Sites → Add Website:
   - **Site name:** `zunzunsite3`
   - **Physical path:** `C:\sites\zunzunsite3\temp` (IIS will serve static files directly from here)
   - **Binding:** port 80 (or 443 with a TLS certificate)

2. Select the site → **URL Rewrite** → Add Rules → Reverse Proxy → enter `localhost:8000` as the inbound rule's backend.

3. IIS will now serve `/temp/static_images/*` (logo, jQuery bundle, favicons) directly as static files and forward everything else to Waitress on port 8000.

### TLS

For a production cert, use `win-acme` (https://www.win-acme.com/) to issue a Let's Encrypt certificate and bind it to the IIS site on port 443.

## Phase 5 — Operational notes

### Logs

- **Waitress stdout/stderr:** `C:\sites\zunzunsite3\waitress.log` and `waitress.err` (captured by NSSM).
- **Child-process tracebacks:** `C:\sites\zunzunsite3\temp\{pid}.log` — one file per failed fit child. Rotate with a scheduled task.
- **IIS access logs:** `C:\inetpub\logs\LogFiles\` (standard W3C format).

### Service management

```powershell
nssm restart zunzunsite3   # after deploying new code
nssm status zunzunsite3    # check if it's running
Services.msc               # GUI alternative
```

### Child process count

During a fit, Task Manager → Details shows:
- 1 `waitress-serve.exe` (the service)
- 1 `python.exe` (the spawned `_run_fit_child`)
- Up to 4 additional `python.exe` (pyeq3 Pool workers; capped at 4 on Windows by `get_parallel_process_count`)

If you see more than 6 Python processes during a single fit, something is wrong — check for leaked children from crashed requests.

### Pagefile sizing — important

Each spawned Pool worker commits ~750 MB of virtual memory (re-imports numpy + scipy + pyeq3 + OpenBLAS thread workspace from scratch). A single fit uses up to 5 such processes. Multi-user concurrent fits can push total committed memory well past physical RAM.

**Set the pagefile to 2–3× physical RAM** via System Properties → Advanced → Performance → Virtual memory. Default system-managed pagefile is too conservative for this workload; under-sized pagefile produces:

```
ImportError: DLL load failed while importing _flapack:
  The paging file is too small for this operation to complete.
```

### Windows Defender exclusion (strongly recommended)

Windows Defender real-time scanning of `.venv/` during fit imports causes significant latency (can add 10–20 s to each fit). Add the project directory as a scan exclusion:

Settings → Windows Security → Virus & threat protection → Manage settings → Exclusions → Add `C:\sites\zunzunsite3\.venv\`.

### Expected fit runtime

A 2D polynomial-quadratic fit on the sample data completes in ~60–120 seconds on a typical developer box. Compare to Linux fork: ~10–30 seconds on the same hardware. The 2–3× overhead is the cost of spawn-based per-worker imports; this is intrinsic to Windows and not a bug.

## Deployment verification

After the service is running, exercise it end-to-end:

```powershell
cd C:\sites\zunzunsite3
uv run python scripts/smoke_test.py
```

Expected output: `SMOKE OK: fit completed and numeric asserts passed`. This starts a throwaway Waitress on a free port, POSTs a fit, polls for completion, and verifies structural markers in the result HTML — so it's safe to run alongside the production service.
