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
