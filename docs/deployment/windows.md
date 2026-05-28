# Windows deployment

Tested on Windows 11 Pro during the April 2026 cross-platform
migration. The `scripts/smoke_test.py` end-to-end test passes on this
stack.

## Architecture

```
Internet
   │
   ▼
  Caddy (port 80/443, TLS termination, static files, reverse proxy)
   │
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
uv python install 3.14
```

### Caddy

```powershell
winget install --id=CaddyServer.Caddy
```

Verify: `caddy version`. If `winget` doesn't have it, download the
Windows binary from
[caddyserver.com/download](https://caddyserver.com/download) and put
`caddy.exe` somewhere on PATH (e.g. `C:\Tools\caddy\`).

### NSSM (the Non-Sucking Service Manager)

Download from [nssm.cc](https://nssm.cc/) and place `nssm.exe` in a
known location (e.g. `C:\Tools\nssm\`).

## Phase 2 — Site layout

```powershell
mkdir C:\sites\zunzun-ng
cd C:\sites\zunzun-ng
git clone https://github.com/kiloscheffer/zunzun-ng.git .
uv sync --no-dev
uv run python manage.py migrate
```

## Phase 3 — Caddyfile

Copy [`Caddyfile.example`](Caddyfile.example) to
`C:\Caddy\Caddyfile` (or wherever you choose to keep it) and edit:

```powershell
mkdir C:\Caddy
copy C:\sites\zunzun-ng\docs\deployment\Caddyfile.example C:\Caddy\Caddyfile
notepad C:\Caddy\Caddyfile
```

In the Caddyfile, change the hostname and replace the example paths
with the Windows paths (Caddy accepts forward slashes on Windows):

```caddyfile
zunzun-ng.example.com {
    handle_path /static/* {
        root * C:/sites/zunzun-ng/static
        file_server
    }
    handle_path /temp/* {
        root * C:/sites/zunzun-ng/temp
        file_server
    }
    handle_path /CommonProblems/* {
        root * C:/sites/zunzun-ng/commonproblems
        file_server
    }
    @bare_cp path /CommonProblems
    redir @bare_cp /CommonProblems/ permanent
    reverse_proxy 127.0.0.1:8000
}
```

Validate:

```powershell
caddy validate --config C:\Caddy\Caddyfile
```

## Phase 4 — Caddy as a Windows Service via NSSM

```powershell
C:\Tools\nssm\nssm.exe install caddy `
    "C:\Program Files\Caddy\caddy.exe" `
    "run" "--config" "C:\Caddy\Caddyfile"
nssm set caddy AppStdout C:\Caddy\caddy.log
nssm set caddy AppStderr C:\Caddy\caddy.err
nssm set caddy Start SERVICE_AUTO_START
nssm start caddy
```

Adjust the `caddy.exe` path if you installed via winget — typically
`C:\Users\<you>\scoop\apps\caddy\current\caddy.exe` or similar.

Caddy obtains and renews Let's Encrypt certs automatically as long as
the hostname resolves to the machine and ports 80 + 443 are reachable.

## Phase 5 — Waitress as a Windows Service via NSSM

```powershell
C:\Tools\nssm\nssm.exe install zunzun-ng `
    "C:\sites\zunzun-ng\.venv\Scripts\waitress-serve.exe" `
    "--listen=127.0.0.1:8000" "wsgi:application"
nssm set zunzun-ng AppDirectory C:\sites\zunzun-ng
nssm set zunzun-ng AppStdout C:\sites\zunzun-ng\waitress.log
nssm set zunzun-ng AppStderr C:\sites\zunzun-ng\waitress.err
nssm set zunzun-ng Start SERVICE_AUTO_START
nssm start zunzun-ng
```

Verify Waitress responds directly (before checking through Caddy):

```powershell
curl.exe http://127.0.0.1:8000/
```

Should return the homepage HTML (~30 KB).

## Phase 6 — Operational notes

### Logs

- **Caddy:** `C:\Caddy\caddy.log` and `caddy.err` (captured by NSSM).
- **Waitress stdout/stderr:** `C:\sites\zunzun-ng\waitress.log` and
  `waitress.err` (captured by NSSM).
- **Child-process tracebacks:** `C:\sites\zunzun-ng\temp\{pid}.log`
  — one file per failed fit child. Rotate with a scheduled task.

### Service management

```powershell
nssm restart zunzun-ng    # after deploying new code
nssm restart caddy        # after editing the Caddyfile
nssm status zunzun-ng     # check if running
Services.msc              # GUI alternative
```

### Pagefile sizing — important

Each spawned worker uses ~140 MB RSS as of 2026-05-28 (Python 3.14 +
numpy 2.4 + scipy 1.17 with the persistent `FitPool` and single-threaded
BLAS — `OMP/OPENBLAS/MKL_NUM_THREADS=1` injected by `FitPool.__init__`).
A single fit auto-detects worker count as `min(cpu_count, available_RAM
/ 200 MB)` — on a 22-core 32 GB box that's 22 workers, total ~3-4 GB RSS
during the parallel phase. Multi-user concurrent fits multiply this.

**Set the pagefile to 2–3× physical RAM** via System Properties →
Advanced → Performance → Virtual memory. Default system-managed
pagefile is too conservative for this workload; under-sized pagefile
produces:

```
ImportError: DLL load failed while importing _flapack:
  The paging file is too small for this operation to complete.
```

### Windows Defender exclusion (strongly recommended)

Windows Defender real-time scanning of `.venv/` during fit imports
causes significant latency (can add 10–20 s to each fit). Add the
project directory as a scan exclusion:

Settings → Windows Security → Virus & threat protection → Manage
settings → Exclusions → Add `C:\sites\zunzun-ng\.venv\`.

### Expected fit runtime

A 2D polynomial-quadratic fit on the sample data completes in
~60–120 seconds on a typical developer box. Compare to Linux fork:
~10–30 seconds on the same hardware. The 2–3× overhead is the cost
of spawn-based per-worker imports; intrinsic to Windows, not a bug.

## Deployment verification

After both services are running, exercise the site end-to-end:

```powershell
cd C:\sites\zunzun-ng
uv run python scripts/smoke_test.py
```

Expected: `SMOKE OK: all scenarios passed`. The smoke test starts a
throwaway Waitress on a free port and POSTs fits — safe to run
alongside the production service.
