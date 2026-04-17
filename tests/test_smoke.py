"""Sanity test: pytest runs, Django is importable, settings are loaded."""
from django.conf import settings


def test_django_settings_loaded():
    assert settings.DEBUG in (True, False)
    assert "zunzun" in settings.INSTALLED_APPS


def test_python_stdlib_available():
    import multiprocessing
    import pickle
    assert multiprocessing.get_all_start_methods()
