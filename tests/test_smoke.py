"""Sanity test: pytest runs, Django settings are loaded, and the
multiprocessing start methods the spawn-based architecture depends on
are actually available.
"""

import multiprocessing
import os
import pickle

from django.conf import settings


def test_django_settings_loaded():
    # Reaching INSTALLED_APPS proves settings are configured; the
    # membership check verifies it's the project's settings module
    # rather than a fallback default.
    assert "zunzun" in settings.INSTALLED_APPS


def test_database_path_is_absolute():
    # The SQLite session DB path must be absolute so it resolves to the
    # same file regardless of the process working directory: a service
    # manager (systemd/launchd/NSSM) can launch from a different cwd than
    # the repo root, and a relative path would silently create/use a
    # second, empty DB there — missing tables, split state.
    #
    # Load settings.py FRESH from disk rather than reading
    # django.conf.settings.DATABASES: pytest-django replaces the configured
    # NAME with an in-memory test DB ('file:memorydb_default?...'), so the
    # live setting never reflects the file's value during a test run. A
    # fresh exec recomputes NAME from the module's own __file__, which is
    # exactly the cwd-independence guarantee under test.
    import importlib.util

    module_spec = importlib.util.find_spec(settings.SETTINGS_MODULE)
    assert module_spec is not None and module_spec.origin, "cannot locate settings module"
    spec = importlib.util.spec_from_file_location("_settings_under_test", module_spec.origin)
    assert spec is not None and spec.loader is not None
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)

    db_name = fresh.DATABASES["default"]["NAME"]
    assert os.path.isabs(db_name), f"DB NAME must be absolute, got: {db_name!r}"


def test_multiprocessing_spawn_available():
    # The cross-platform migration replaces os.fork() with spawn,
    # which must be present on every target OS.
    assert "spawn" in multiprocessing.get_all_start_methods()


def test_pickle_highest_protocol_available():
    # multiprocessing.Process(spawn) pickles arguments at HIGHEST_PROTOCOL;
    # the ChildPayload round-trip tests in later tasks rely on this.
    assert pickle.HIGHEST_PROTOCOL >= 5
