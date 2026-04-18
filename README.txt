Welcome to zunzunsite3, a Django site in Python 3 for curve fitting 2D
and 3D data that can output source code in several computing languages
and run a genetic algorithm for initial parameter estimation. Includes
orthogonal distance and relative error regressions. Generates PDF files
and surface animations. Based on code from zunzun.com.

Python dependencies are managed with uv (https://docs.astral.sh/uv/).
To install uv, see https://docs.astral.sh/uv/getting-started/install/
-- or on Debian/Ubuntu: apt-get install pipx && pipx install uv.

Once uv is on your PATH, create the virtual environment and install
Django, pyeq3, scipy, matplotlib, reportlab, psutil, bs4, numpy:

    uv sync

System dependencies for PDF and GIF output are not Python packages
and must be installed separately. On Debian and Ubuntu:

    apt-get install imagemagick gifsicle

First-time setup creates the session database:

    uv run python manage.py migrate

Then run the django development server with:

    uv run python manage.py runserver

and open the url http://127.0.0.1:8000/ in a browser. Cool!


Cross-platform: zunzunsite3 runs natively on Linux, macOS, and Windows
as of April 2026. The original os.fork() architecture was replaced
with multiprocessing.Process(spawn) so the code no longer depends on
Unix-style process forking.

For production deployment recipes per platform, see docs/deployment/.
The recommended stack is nginx/IIS + Waitress (works on all three OSes).

If you have existing Linux deployments: gunicorn still works with
--worker-class sync --threads 1 (multi-threaded workers reintroduce
fork-safety hazards in view code that spawns subprocesses). Apache +
mod_wsgi works under the same threads=1 constraint. Waitress is now
the recommended cross-platform choice.

An end-to-end smoke test is available:

    uv run python scripts/smoke_test.py

It starts a throwaway Waitress, runs a 2D polynomial-quadratic fit
end-to-end, and asserts the fit results rendered correctly. Useful
for verifying a fresh deployment or confirming a dev setup works.

The FunkLoad functional tests in funkload_tests/ require a separate
install. FunkLoad's setup.py depends on ez_setup which has been
removed from modern setuptools, so it cannot be installed under the
uv-managed environment. scripts/smoke_test.py provides a lighter
substitute using pytest-style HTTP assertions. See CLAUDE.md > Tests
for details.
