"""Pytest config: guarantee Django is configured before any test imports.

pytest-django normally handles this via DJANGO_SETTINGS_MODULE, but we
keep an explicit django.setup() call here as a belt-and-suspenders in
case a test runs before django_settings is autodiscovered.
"""
import django


def pytest_configure(config):
    django.setup()
