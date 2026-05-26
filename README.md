# ZunZunNG

A Django site for 2D and 3D nonlinear curve and surface fitting via the [`pyeq3`](https://github.com/kiloscheffer/pyeq3-ng) library — with genetic-algorithm initial parameter estimation, orthogonal-distance and relative-error regressions, source-code generation in several languages, PDF reports, and surface animations.

Hosted at [github.com/kiloscheffer/zunzun-ng](https://github.com/kiloscheffer/zunzun-ng).

## What it does

- Fits a large catalogue of named 2D and 3D equations to user-supplied data.
- Uses Differential Evolution (a genetic algorithm) to find good starting points before handing off to a non-linear solver — so you don't need to guess initial parameter values.
- Ranks candidate equations by AIC, SSQ, and other fit statistics (the *Function Finder* flow).
- Emits fitted-coefficient source code in C++, C#, Fortran 90, Java, JavaScript, Julia, and Python.
- Generates a PDF report per fit (cover page, statistics, scatterplots, histograms) and animated GIFs for 3D surface visualisations.
- Handles outliers, weighted fits, splines, and user-defined functions.

## Development setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/). To install uv, see the [uv install guide](https://docs.astral.sh/uv/getting-started/install/) — or on Debian/Ubuntu: `apt-get install pipx && pipx install uv`.

```bash
uv sync                                   # create .venv, install deps
uv run python manage.py migrate           # one-time: create the session DB
uv run python manage.py runserver         # http://127.0.0.1:8000/
```

## Production

```bash
uv sync --no-dev
uv run waitress-serve --listen=127.0.0.1:8000 wsgi:application
```

Per-platform recipes (systemd unit, launchd plist, IIS + NSSM) live in [`docs/deployment/`](docs/deployment/). Waitress is the recommended cross-platform WSGI server; legacy gunicorn / Apache + mod_wsgi setups still work on Linux but require `threads=1` to avoid fork-safety hazards in view code that spawns subprocesses.

## Testing

```bash
uv run pytest tests/                      # 78 unit tests, ~20s
uv run python scripts/smoke_test.py       # end-to-end smoke, ~1–5 min
```

The smoke script starts a throwaway Waitress, POSTs a real fit, polls for completion, and asserts structural markers in the result. The legacy FunkLoad suite under `funkload_tests/` is not runnable under the uv-managed Python 3.14 environment; see [`CLAUDE.md`](CLAUDE.md) for details.

## Cross-platform

ZunZunNG runs natively on Linux, macOS, and Windows. The original `os.fork()` architecture was replaced with `multiprocessing.Process(spawn)` so the code no longer depends on Unix-style process forking. Platform-specific calls (load average, process priority, zombie reap) are isolated in [`zunzun/platform_compat.py`](zunzun/platform_compat.py).

## About this fork

ZunZunNG ("Next Generation") is a permanent fork of James R. Phillips's [`zunzunsite3`](https://bitbucket.org/zunzuncode/zunzunsite3) (Copyright © 2016 James R. Phillips, BSD-2-clause; dormant since 2020), modernized for:

- **Python 3.14 / Django 6.0** (was Python 3.x / Django 2.2).
- **Cross-platform deployment** (Linux, macOS, Windows) via the spawn-based multiprocessing migration.
- **scipy.odr removal** via the companion [`pyeq3-ng`](https://github.com/kiloscheffer/pyeq3-ng) fork — `scipy.odr` was deprecated in scipy 1.17 and slated for removal in 1.19.
- **Pure-Python animated GIFs** via matplotlib's `PillowWriter`, replacing the previous `imagemagick` + `gifsicle` system-binary dependency.

The original copyright notice in [`LICENSE.txt`](LICENSE.txt) is retained per the BSD-2-clause terms. James R. Phillips's prose in the "About" page is preserved verbatim.

For deeper architecture notes — the spawn-based long-running-process pattern, the three parallel session stores, the `ChildPayload` contract — see [`CLAUDE.md`](CLAUDE.md).

## License

BSD-2-clause. See [`LICENSE.txt`](LICENSE.txt).
