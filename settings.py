import os

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

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
FEEDBACK_EMAIL_ADDRESS = ""  # for any user feedback

SESSION_COOKIE_NAME = "sessionid"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 5  # 60 seconds * 60 minutes * 24 hours * 5 days

EMAIL_USE_TLS = True  # assuming gmail
EMAIL_PORT = 587  # assuming gmail
EMAIL_HOST = "smtp.gmail.com"  # assuming gmail
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""

MANAGERS = ADMINS

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "session_db/db.sqlite3",
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

ROOT_PATH = os.path.dirname(__file__)

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(ROOT_PATH, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {},
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

# If True (default — convenient for local single-user development), one
# user can launch multiple fits concurrently. If False (recommended for
# public-facing deployments), a second fit POST from the same session is
# refused with a "fit in progress" HTML response while the first is still
# running.
ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER = True
