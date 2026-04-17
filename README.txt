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


NOTES: the code uses Unix-style process forking, and this is not
available on the Windows operating system.

My tests show that while both mod_wsgi and gunicorn work fine for
Django production servers, the uwsgi process model would not allow
os.fork() calls to work as required for this software.

The FunkLoad functional tests in funkload_tests/ require a separate
install. FunkLoad's setup.py depends on ez_setup which has been
removed from modern setuptools, so it cannot be installed under the
uv-managed environment; see CLAUDE.md > Tests for current guidance.
