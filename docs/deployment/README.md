# Deployment recipes

Production deployment is documented per platform. Pick your target:

- [Linux](linux.md) — Caddy → Waitress, supervised by systemd
- [macOS](macos.md) — Caddy → Waitress, supervised by launchd
- [Windows](windows.md) — Caddy → Waitress, both supervised by NSSM

All three use the same two-process stack:

- **[Caddy](https://caddyserver.com/)** as the edge reverse proxy. It serves the static URL prefixes (`/static/`, `/temp/`, `/CommonProblems/`) directly from disk and proxies everything else to Waitress. Automatic HTTPS via Let's Encrypt is built in — no certbot, no win-acme, no manual cert renewal.
- **[Waitress](https://docs.pylonsproject.org/projects/waitress/)** as the Python WSGI server, listening on `127.0.0.1:8000`. It runs natively on every supported OS without per-platform shims.

The single shared [`Caddyfile.example`](Caddyfile.example) works on all three platforms — the only differences between recipes are the install command, the on-disk paths, and the service supervisor.

## Minimum stack

- Python 3.14 (uv-managed; see `README.md`)
- `uv sync --no-dev` to install production dependencies
- Caddy on `PATH` (or installed as a service)
- A process supervisor appropriate to the OS (systemd, launchd, NSSM)

No external system binaries beyond Caddy itself — animated GIF output is pure-Python via matplotlib's `PillowWriter` since the April 2026 migration.

The one-time `uv run python manage.py migrate` (see the top-level `README.md`) creates `session_db/db.sqlite3` with both the `django_session` table and the `zunzun_lrpstatus` status table. Without it, every fit dispatch fails because the session/status backends have nowhere to write.

## Upgrades and redeploys

**Drain in-progress fits before deploying.** A fit's status lives in a per-dispatch `zunzun_lrpstatus` row, pointed at by `lrp_status_pk` in the user's session. A fit dispatched by the *previous* code that is still running across a restart is not migrated: the spawned child keeps running, but its status page may not resolve cleanly under the new code. Before restarting Waitress for an upgrade, let active fits finish (or accept that any in-flight fit must be re-run by the user). Fits are short (seconds to a few minutes), so a brief drain window before restart is enough. This is standard practice for the spawn-LRP architecture and avoids carrying transitional fallback code in the request path. See `BACKLOG.md` ("Pre-migration in-flight fits are not resumed across deploy").

## Why Caddy

Three reasons it ended up the default after the cross-platform migration:

1. **Single config, three platforms.** The same Caddyfile runs unmodified on Linux, macOS, and Windows. Compare to nginx (no first-class Windows build) + IIS (Windows only, XML config) which previously needed two separate recipes.
2. **Automatic HTTPS.** Caddy obtains and renews Let's Encrypt certs without any extra config — just point a hostname at the box and open ports 80/443. nginx + certbot or IIS + win-acme both require multi-step setup and renewal cron jobs.
3. **Sensible defaults for static + reverse-proxy.** `file_server` auto-serves `index.html` for directory requests (handy for `/CommonProblems/`), and `reverse_proxy` preserves the `Host` header without ceremony.

## Cross-platform reality check

ZunZunNG runs natively on Linux, macOS, and Windows as of the April 2026 migration. A few things to know before sizing a production box:

- **Fit memory footprint scales with worker count.** `spawn` is used on every platform (Linux included — there is no `fork` path), so each pyeq3 worker is a full Python process with no copy-on-write sharing to lean on (~140 MB RSS, measured 2026-05-28 on Python 3.14 + numpy 2.4 + scipy 1.17 with the persistent `FitPool` and single-threaded BLAS). Per-fit worker count is auto-detected as `min(cpu_count, available_RAM_KiB / 200_000)` by `zunzun.parallel_pool.resolve_max_workers`. Override via the `ZUNZUN_MAX_WORKERS` env var or `settings.MAX_PARALLEL_WORKERS`. On a low-RAM box, `ZUNZUN_MAX_WORKERS=4` is a safe emergency throttle.
- **Windows needs a generous pagefile.** On a 16 GB box with the default system-managed pagefile, a single concurrent fit is fine, but a few concurrent users can exhaust virtual memory. Size pagefile at 2–3× physical RAM for production, and/or exclude `.venv/` from Defender real-time scanning (see [`windows.md`](windows.md)).
- **Fit runtime is roughly platform-parity between Windows and Linux.** Both run the same `spawn`-based persistent worker pool — there is no `fork` path — so once the pool is warm the CPU-bound numpy/scipy/pyeq3 fitting dominates and the host OS barely matters. A reference 2D Function Finder run (863 non-linear + 263 linear fits, 22 workers) on one box measured **`00:00:54` under WSL/Linux vs `00:01:00` on native Windows** — ~10%, not the multiples sometimes assumed for spawn. The same run on the *old* fork-based code under WSL took `00:01:08`, so the spawn rewrite is faster than the fork architecture it replaced, not slower. Windows' main one-time cost is Defender scanning `.venv` during imports — add the exclusion (see [`windows.md`](windows.md)). Full benchmark table in [`windows.md`](windows.md) § Expected fit runtime.

## Docker

If you're containerized, pick a `python:3.14-slim` base image and follow the [Linux](linux.md) recipe inside the container. Docker itself handles cross-platform (Linux containers run on all three host OSes via WSL2/Hyper-V on Windows and Virtualization.framework on macOS).

## What isn't documented

- CI/CD pipeline automation — out of scope.
- Kubernetes / orchestration — the Linux systemd unit is the reference; adapt to your orchestrator's unit format.
- Multi-region deployments, load balancing across multiple Waitress instances, horizontal scaling — none are addressed. ZunZunNG is a small research tool; a single Waitress instance behind a single reverse proxy handles its typical load.
