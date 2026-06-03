"""Tests for demo mode: the env-gated hourly fit cap and the watermark plumbing.

Both the view guard and the context processor read the ROOT `settings` module
(`import settings`, the project's no-inner-package layout), so these tests patch
`settings.DEMO_MODE` / `settings.DEMO_MAX_FITS_PER_HOUR` directly via
`mock.patch(..., create=True)` — NOT Django's @override_settings, which patches
the separate django.conf lazy wrapper this code never consults. This mirrors the
existing concurrency-cap tests (tests/test_views_per_user_cap.py).

The autouse `reset_cache` fixture (tests/conftest.py) clears the LocMemCache
before each test, so django-ratelimit per-IP windows do not leak between tests.
"""

import os
from unittest.mock import patch

import pytest


def test_demo_settings_exist_with_sane_types():
    """DEMO_MODE is a bool, DEMO_MAX_FITS_PER_HOUR a positive int. The default
    pins are asserted only when the env vars are unset (robust against a dev
    machine that exports them — same hardening as the _fits_default tests)."""
    import settings

    assert isinstance(settings.DEMO_MODE, bool)
    assert isinstance(settings.DEMO_MAX_FITS_PER_HOUR, int)
    assert settings.DEMO_MAX_FITS_PER_HOUR >= 1

    if "ZUNZUN_DEMO_MODE" not in os.environ:
        assert settings.DEMO_MODE is False
    if "ZUNZUN_DEMO_MAX_FITS_PER_HOUR" not in os.environ:
        assert settings.DEMO_MAX_FITS_PER_HOUR == 4


def test_demo_mode_context_processor_reflects_setting():
    """The processor returns {'demo_mode': settings.DEMO_MODE}. It ignores its
    request arg, so we pass None. Patching the root settings module flips it."""
    from zunzun.context_processors import demo_mode

    with patch("settings.DEMO_MODE", True, create=True):
        assert demo_mode(None) == {"demo_mode": True}
    with patch("settings.DEMO_MODE", False, create=True):
        assert demo_mode(None) == {"demo_mode": False}


@pytest.mark.django_db
def test_body_has_demo_class_when_on(client, mocked_process_start):
    """GET / renders <body class="demo-mode"> when DEMO_MODE is on. mocked_process
    _start no-ops HomePageView's housekeeping child spawn."""
    with patch("settings.DEMO_MODE", True, create=True):
        response = client.get("/")
    assert b'class="demo-mode"' in response.content


@pytest.mark.django_db
def test_body_has_no_demo_class_when_off(client, mocked_process_start):
    """When DEMO_MODE is off the class is empty — proves zero visual change."""
    with patch("settings.DEMO_MODE", False, create=True):
        response = client.get("/")
    assert b'class="demo-mode"' not in response.content
    assert b'class=""' in response.content
