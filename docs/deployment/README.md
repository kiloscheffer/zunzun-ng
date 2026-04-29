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

- Python 3.14 (uv-managed; see `README.txt`)
- `uv sync --no-dev` to install production dependencies
- Caddy on `PATH` (or installed as a service)
- A process supervisor appropriate to the OS (systemd, launchd, NSSM)

No external system binaries beyond Caddy itself — animated GIF output is pure-Python via matplotlib's `PillowWriter` since the April 2026 migration.

## Why Caddy

Three reasons it ended up the default after the cross-platform migration:

1. **Single config, three platforms.** The same Caddyfile runs unmodified on Linux, macOS, and Windows. Compare to nginx (no first-class Windows build) + IIS (Windows only, XML config) which previously needed two separate recipes.
2. **Automatic HTTPS.** Caddy obtains and renews Let's Encrypt certs without any extra config — just point a hostname at the box and open ports 80/443. nginx + certbot or IIS + win-acme both require multi-step setup and renewal cron jobs.
3. **Sensible defaults for static + reverse-proxy.** `file_server` auto-serves `index.html` for directory requests (handy for `/CommonProblems/`), and `reverse_proxy` preserves the `Host` header without ceremony.

## Cross-platform reality check

ZunZunNG runs natively on Linux, macOS, and Windows as of the April 2026 migration. A few things to know before sizing a production box:

- **Fit memory footprint scales with worker count.** Each pyeq3 Pool worker under Windows/macOS spawn is a full Python process (~750 MB committed VM) because the start method re-imports numpy/scipy/pyeq3 from scratch. On Linux fork, workers are ~50 MB. `platform_compat.get_parallel_process_count` caps at 4 workers on spawn platforms by default to keep the math tractable.
- **Windows needs a generous pagefile.** On a 16 GB box with the default system-managed pagefile, a single concurrent fit is fine, but a few concurrent users can exhaust virtual memory. Size pagefile at 2–3× physical RAM for production, and/or exclude `.venv/` from Defender real-time scanning (see [`windows.md`](windows.md)).
- **Fit runtime on Windows is 2–3× longer than Linux for the same fit.** Spawn per-worker import overhead. If you need Linux-like performance, deploy on Linux.

## Docker

If you're containerized, pick a `python:3.14-slim` base image and follow the [Linux](linux.md) recipe inside the container. Docker itself handles cross-platform (Linux containers run on all three host OSes via WSL2/Hyper-V on Windows and Virtualization.framework on macOS).

## What isn't documented

- CI/CD pipeline automation — out of scope.
- Kubernetes / orchestration — the Linux systemd unit is the reference; adapt to your orchestrator's unit format.
- Multi-region deployments, load balancing across multiple Waitress instances, horizontal scaling — none are addressed. ZunZunNG is a small research tool; a single Waitress instance behind a single reverse proxy handles its typical load.
