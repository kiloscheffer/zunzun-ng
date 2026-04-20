# Deployment recipes

Production deployment is documented per platform. Pick your target:

- [Linux](linux.md) — nginx → Waitress (or gunicorn sync workers)
- [macOS](macos.md) — nginx → Waitress, supervised by launchd
- [Windows](windows.md) — IIS + Waitress via NSSM

All three use **[Waitress](https://docs.pylonsproject.org/projects/waitress/)** as the Python WSGI server because it runs natively on every supported OS. The reverse proxy (nginx or IIS) handles TLS termination, static asset caching, and URL routing.

## Minimum stack

- Python 3.14 (uv-managed; see `README.txt`)
- `uv sync --no-dev` to install production dependencies
- A reverse proxy for TLS + static files (nginx or IIS)
- A process supervisor appropriate to the OS (systemd, launchd, NSSM)
- `imagemagick` and `gifsicle` on `PATH` (required for animated GIF output; the site logs a prominent warning at startup if either is missing)

## Cross-platform reality check

ZunZunNG runs natively on Linux, macOS, and Windows as of the April 2026 migration. A few things to know before sizing a production box:

- **Fit memory footprint scales with worker count.** Each pyeq3 Pool worker under Windows/macOS spawn is a full Python process (~750 MB committed VM) because the start method re-imports numpy/scipy/pyeq3 from scratch. On Linux fork, workers are ~50 MB. `platform_compat.get_parallel_process_count` caps at 4 workers on spawn platforms by default to keep the math tractable.
- **Windows needs a generous pagefile.** On a 16 GB box with the default system-managed pagefile, a single concurrent fit is fine, but a few concurrent users can exhaust virtual memory. Size pagefile at 2–3× physical RAM for production, and/or exclude `.venv/` from Defender real-time scanning (see `windows.md`).
- **Fit runtime on Windows is 2–3× longer than Linux for the same fit.** Spawn per-worker import overhead. If you need Linux-like performance, deploy on Linux.

## Docker

If you're containerized, pick a `python:3.14-slim` base image and follow the [Linux](linux.md) recipe inside the container. Docker itself handles cross-platform (Linux containers run on all three host OSes via WSL2/Hyper-V on Windows and Virtualization.framework on macOS).

## What isn't documented

- CI/CD pipeline automation — out of scope.
- Kubernetes / orchestration — the Linux systemd unit is the reference; adapt to your orchestrator's unit format.
- Multi-region deployments, load balancing across multiple Waitress instances, horizontal scaling — none are addressed. ZunZunNG is a small research tool; a single Waitress instance behind a single reverse proxy handles its typical load.
