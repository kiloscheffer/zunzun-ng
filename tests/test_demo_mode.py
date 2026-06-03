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


# A minimal valid 2D quadratic fit POST, mirroring tests/test_ratelimit.py.
_FIT_FIELDS = {
    "commaConversion": "I",
    "graphSize": "320x240",
    "animationSize": "0x0",
    "scientificNotationX": "AUTO",
    "scientificNotationY": "AUTO",
    "dataNameX": "X",
    "dataNameY": "Y",
    "graphScaleRadioButtonX": "0.050",
    "graphScaleRadioButtonY": "0.050",
    "logLinX": "LIN",
    "logLinY": "LIN",
    "logLinZ": "LIN",
    "fittingTarget": "SSQABS",
    "textDataEditor": "X Y\n1 2\n2 4\n3 6\n4 8\n5 10\n",
}
_FIT_URL = "/FitEquation__F__/2/Polynomial/2nd Order (Quadratic)/"


def _seed_cookie_test(client):
    """LongRunningProcessView requires cookie_test on the session (normally set
    by HomePageView) before a POST reaches the dispatch/spawn branch."""
    session = client.session
    session["cookie_test"] = 1
    session.save()


@pytest.mark.django_db
def test_fifth_fit_post_blocked_in_demo_mode(client, mocked_process_start):
    """With DEMO_MODE on and the cap at 4, POSTs 1-4 dispatch (302) and the 5th
    is refused with HTTP 429 rendered from demo_limit_reached.html.

    The clock is frozen (django_ratelimit.core.time) so all 5 POSTs share one
    hourly window; the concurrency caps are patched high so that separate gate
    never interferes; mocked_process_start no-ops the real child spawn."""
    _seed_cookie_test(client)
    with (
        patch("django_ratelimit.core.time") as ratelimit_clock,
        patch("settings.DEMO_MODE", True, create=True),
        patch("settings.DEMO_MAX_FITS_PER_HOUR", 4, create=True),
        patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 99, create=True),
        patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True),
    ):
        ratelimit_clock.time.return_value = 1_700_000_000
        for i in range(4):
            response = client.post(_FIT_URL, data=_FIT_FIELDS, HTTP_HOST="testserver")
            assert response.status_code == 302, f"fit {i + 1} should dispatch (302)"

        response = client.post(_FIT_URL, data=_FIT_FIELDS, HTTP_HOST="testserver")
        assert response.status_code == 429
        assert "zunzun/demo_limit_reached.html" in [t.name for t in response.templates]
        assert b"demo limit" in response.content.lower()


@pytest.mark.django_db
def test_demo_disabled_does_not_block_fifth_post(client, mocked_process_start):
    """DEMO_MODE off (default): a 5th POST in the window still dispatches (302) —
    the hourly cap is inert. (5 < 12, so the unrelated 12/m limiter never trips.)"""
    _seed_cookie_test(client)
    with (
        patch("django_ratelimit.core.time") as ratelimit_clock,
        patch("settings.DEMO_MODE", False, create=True),
        patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 99, create=True),
        patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True),
    ):
        ratelimit_clock.time.return_value = 1_700_000_000
        for i in range(5):
            response = client.post(_FIT_URL, data=_FIT_FIELDS, HTTP_HOST="testserver")
            assert response.status_code == 302, f"fit {i + 1} should dispatch (302)"


@pytest.mark.django_db
def test_demo_cap_honors_env_override(client, mocked_process_start):
    """DEMO_MAX_FITS_PER_HOUR=2 moves the block to the 3rd POST, proving the
    setting (not a hardcoded 4) drives the rate string."""
    _seed_cookie_test(client)
    with (
        patch("django_ratelimit.core.time") as ratelimit_clock,
        patch("settings.DEMO_MODE", True, create=True),
        patch("settings.DEMO_MAX_FITS_PER_HOUR", 2, create=True),
        patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 99, create=True),
        patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True),
    ):
        ratelimit_clock.time.return_value = 1_700_000_000
        for i in range(2):
            response = client.post(_FIT_URL, data=_FIT_FIELDS, HTTP_HOST="testserver")
            assert response.status_code == 302, f"fit {i + 1} should dispatch (302)"

        response = client.post(_FIT_URL, data=_FIT_FIELDS, HTTP_HOST="testserver")
        assert response.status_code == 429
