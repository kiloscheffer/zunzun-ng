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
