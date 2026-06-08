import os

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

# Absolute path to the project (repo) root — the directory this settings
# module lives in. Anchored on __file__, not the process cwd, so paths
# derived from it (the session DB, templates, static/temp dirs) resolve to
# the same location no matter where a service manager launches the process.
ROOT_PATH = os.path.dirname(os.path.abspath(__file__))

ALLOWED_HOSTS = ["*"]

# this is for serving static files with the django development server
import sys

if "runserver" in sys.argv:
    DEBUG = True
else:
    DEBUG = False

ADMINS = (
    # (ADMIN_NAME, ADMIN_EMAIL_ADDRESS),
)

EXCEPTION_EMAIL_ADDRESS = ""  # for unknown site exceptions

SESSION_COOKIE_NAME = "sessionid"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 5  # 60 seconds * 60 minutes * 24 hours * 5 days

# numpy-aware session serializer. pyeq3 produces numpy scalars / arrays
# (coefficient arrays, ranking tuples) that Django's default JSONSerializer
# cannot encode. NumpySessionSerializer coerces them at session.save() time
# so LRP save sites don't each have to remember an explicit cast. See
# zunzun/session_helpers.py.
SESSION_SERIALIZER = "zunzun.session_helpers.NumpySessionSerializer"

EMAIL_USE_TLS = True  # assuming gmail
EMAIL_PORT = 587  # assuming gmail
EMAIL_HOST = "smtp.gmail.com"  # assuming gmail
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""

MANAGERS = ADMINS

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(ROOT_PATH, "session_db", "db.sqlite3"),
        "OPTIONS": {"timeout": 5},  # in case database is busy or slow
    }
}

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# NOTE:vIf running in a Windows environment this must be set to the
# vsame as your system time zone.
TIME_ZONE = "America/Chicago"

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = "en-us"

SITE_ID = 1  # we're number one! we're number one!

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = False

# Make this unique, and don't share it with anybody.
SECRET_KEY = "super-secret-key"

MIDDLEWARE = [
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # 'django.contrib.auth.middleware.AuthenticationMiddleware',
    "zunzun.middleware.CommonToAllViewsMiddleware",
]

ROOT_URLCONF = "urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(ROOT_PATH, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "zunzun.context_processors.demo_mode",
            ],
        },
    },
]
INSTALLED_APPS = (
    #    'django.contrib.auth',
    #    'django.contrib.contenttypes',
    "django.contrib.sessions",
    #    'django.contrib.sites',
    "django.contrib.staticfiles",
    "zunzun",
)

# Static files (committed assets that ship with the codebase: CSS, JS,
# logos, favicon). Served at /static/ in dev by django.contrib.staticfiles
# during runserver, and by the reverse proxy (nginx/IIS) in production.
STATIC_URL = "/static/"
STATIC_FILES_DIR = os.path.join(ROOT_PATH, "static")
STATICFILES_DIRS = (STATIC_FILES_DIR,)

# Media / runtime-generated files (PDFs, graphs, animations written by
# spawned fit children). Served at /temp/ for backward compatibility with
# generated output URLs that may be embedded in PDFs already in the wild.
# In dev, urls.py has to add explicit serving for MEDIA_URL since the
# staticfiles app doesn't auto-serve media. In production, nginx/IIS
# handles it directly.
MEDIA_URL = "/temp/"
TEMP_FILES_DIR = os.path.join(ROOT_PATH, "temp")
MEDIA_ROOT = TEMP_FILES_DIR
MAX_TEMP_DIR_SIZE_IN_MBYTES = 500  # default 500 megabytes maximum

# Hard age ceiling (seconds) for FunctionFinder ranking LRPStatus rows — a
# safety net, env-overridable. FF ranking rows are retained on the disk-bounded
# clock via a temp/ffanchor marker (see views._sweep_orphaned_terminal_rows),
# but that marker is a few bytes while the ranking's real payload lives in
# LRPDispatchData (a DB row, NOT counted toward MAX_TEMP_DIR_SIZE_IN_MBYTES).
# So an FF-heavy / low-artifact workload could keep temp/ under quota forever,
# never trip the size-prune that evicts the marker, and let ranking rows + DB
# payloads grow unbounded. _sweep_aged_rows reaps FF ranking rows older than
# this regardless of the marker. Default 90 days (>> SESSION_COOKIE_AGE) keeps
# shared /Results/<token>/ links alive far longer than session age while
# bounding growth.
FF_RANKING_MAX_AGE = int(
    os.environ.get("ZUNZUN_FF_RANKING_MAX_AGE_SECONDS", str(60 * 60 * 24 * 90))
)

# Per-LRP trace logging. Default WARNING (silent in production). Bump to
# DEBUG to see per-step tracing through fit dispatch, data validation,
# and report generation. Set via env var ZUNZUN_LRP_LOG_LEVEL=DEBUG
# without editing source.
#
# Spawn-child trace output lands in temp/{pid}.log via the FileHandler
# installed by `_setup_child_root_logging` at the top of
# `_run_fit_child`. Without that early install, DEBUG messages from
# normal-path code (PerformAllWork, the per-step trace points in the
# LRP tree) would be dropped — only exception handlers add the file
# handler downstream, by which point any successful trace points have
# already fired.
#
# Parent-process trace output is not routed by default (Django's root
# logger has no handlers). To see DEBUG messages from the parent's
# share of LRP code (e.g. SetInitialStatusDataIntoSessionVariables),
# add a handler in this LOGGING dict or via runserver --verbosity.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {
        "zunzun.LongRunningProcess": {
            "level": os.environ.get("ZUNZUN_LRP_LOG_LEVEL", "WARNING"),
            "propagate": True,
        },
    },
}

# Maximum worker processes a single fit may use concurrently. Used by the
# per-fit FitPool inside the LRP child. Resolution order:
#   1. ZUNZUN_MAX_WORKERS env var (must be positive int).
#   2. MAX_PARALLEL_WORKERS below (must be positive int).
#   3. Auto-detect min(cpu_count, available_RAM_KiB / 200_000).
# Result is always clamped to the hardware ceiling. Set None to disable
# this layer of override and rely on env-var-or-auto-detect.
MAX_PARALLEL_WORKERS = None


# Concurrency backpressure for fits. Defaults are DEBUG-aware: a permissive dev
# posture (10/10) under runserver so a developer can run several fits / a
# FunctionFinder ranking at once, and the conservative public posture (1/4)
# under any non-runserver server (Waitress/WSGI prod, smoke, pytest). Env vars
# override either default — including the personal-production case (a Waitress
# box only the owner uses that wants the relaxed posture). On localhost every
# request shares IP 127.0.0.1, so the per-IP cap is the real dev ceiling — both
# rise together. Enforced by the per-fit gate in views.LongRunningProcessView
# (per-session by owner_session_key, per-IP by owner_ip), counting live
# LRPStatus rows.
def _fits_default(env_var, dev_default, prod_default, debug):
    """Env var wins; otherwise a permissive dev default vs the safe prod default."""
    return int(os.environ.get(env_var, str(dev_default if debug else prod_default)))


MAX_CONCURRENT_FITS_PER_SESSION = _fits_default(
    "ZUNZUN_MAX_CONCURRENT_FITS_PER_SESSION", 10, 1, DEBUG
)
MAX_CONCURRENT_FITS_PER_IP = _fits_default("ZUNZUN_MAX_CONCURRENT_FITS_PER_IP", 10, 4, DEBUG)


# Demo-mode posture (public showcase). OFF by default; ZUNZUN_DEMO_MODE=1 turns
# the instance into a demo: (a) caps fit-runs per IP per hour and (b) renders a
# faint diagonal "DEMO" watermark behind page content (see static/custom.css and
# zunzun/context_processors.py). Independent of DEBUG — a demo box runs under
# Waitress (DEBUG=False) just like prod. The hourly ceiling is enforced only when
# DEMO_MODE is on, by the in-view guard at the top of views.LongRunningProcessView;
# it is env-overridable to match the MAX_CONCURRENT_FITS_PER_IP philosophy.
DEMO_MODE = os.environ.get("ZUNZUN_DEMO_MODE", "0") == "1"
DEMO_MAX_FITS_PER_HOUR = int(os.environ.get("ZUNZUN_DEMO_MAX_FITS_PER_HOUR", "4"))
