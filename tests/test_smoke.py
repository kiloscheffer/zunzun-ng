"""Sanity test: pytest runs, Django settings are loaded, and the
multiprocessing start methods the spawn-based architecture depends on
are actually available.
"""
import multiprocessing
import pickle

from django.conf import settings


def test_django_settings_loaded():
    # Reaching INSTALLED_APPS proves settings are configured; the
    # membership check verifies it's the project's settings module
    # rather than a fallback default.
    assert "zunzun" in settings.INSTALLED_APPS


def test_multiprocessing_spawn_available():
    # The cross-platform migration replaces os.fork() with spawn,
    # which must be present on every target OS.
    assert "spawn" in multiprocessing.get_all_start_methods()


def test_pickle_highest_protocol_available():
    # multiprocessing.Process(spawn) pickles arguments at HIGHEST_PROTOCOL;
    # the ChildPayload round-trip tests in later tasks rely on this.
    assert pickle.HIGHEST_PROTOCOL >= 5
