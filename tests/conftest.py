"""Pytest config: ensure DJANGO_SETTINGS_MODULE is set when pytest is invoked
from contexts that don't read pyproject.toml [tool.pytest.ini_options].

The ini file handles the common case. This belt-and-suspenders covers IDE
runners and programmatic pytest invocations where the ini config may be
bypassed. django.setup() is idempotent (apps.populate short-circuits on
apps.ready), so calling it again is safe even if pytest-django already
configured the app registry.
"""

import os

import django


def pytest_configure(config):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
    django.setup()


from unittest.mock import patch

import pytest


@pytest.fixture
def client(db):
    """Django test Client with a fresh session. Uses pytest-django's
    `db` fixture to ensure the session DB tables exist (via migrations
    run once per test session).
    """
    from django.test import Client

    return Client()


@pytest.fixture
def mocked_process_start():
    """Patches multiprocessing.Process.start to a no-op for view tests
    that exercise the spawn dispatch path. Each call is recorded on
    the returned mock so tests can assert dispatch behavior.

    Without this patch, a POST to /FitEquation__F__/.../ in-test would
    actually spawn a Python subprocess, which is slow and OS-coupled.
    """
    with patch("multiprocessing.context.SpawnProcess.start") as mock_start:
        yield mock_start


@pytest.fixture(autouse=True)
def reset_cache():
    """Clear the process-wide LocMemCache before every test.

    django-ratelimit stores its per-IP request counter in the default cache,
    which pytest-django does NOT reset between tests. Without this, POSTs to
    @ratelimit views (LongRunningProcessView is hit by test_views_per_user_cap,
    test_views_dispatch, test_matrix_selector, test_ratelimit, ...) accumulate
    across the suite on the shared 127.0.0.1 counter. Once a 12/m window fills,
    every later POST trips request.limited and middleware.rate_limit_sleep runs
    a real time.sleep(5.0) — a silent multi-second slowdown and an
    order-dependent flake (see BACKLOG, rate-limit test). Clearing before each
    test gives every test a clean counter (and isolates cache_page entries too).
    """
    from django.core.cache import cache

    cache.clear()
