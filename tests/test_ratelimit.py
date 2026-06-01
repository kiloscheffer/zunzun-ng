"""Rate limit tests.

Asserts that >12 POSTs/minute to a rate-limited view cause the
13th to have request.limited set to True.

Pre-Phase-4 this test FAILS because django_brake is not installed
and the pass-through decorator does not set request.limited.
Post-Phase-4 it PASSES because django-ratelimit sets request.limited.
"""

from unittest.mock import patch

import pytest


@pytest.mark.django_db
def test_thirteenth_rapid_post_is_rate_limited(client, mocked_process_start):
    """12 POSTs succeed, 13th triggers the rate limiter.

    Made hermetic to kill a CI flake (see BACKLOG, "test_thirteenth_rapid_post
    _is_rate_limited flakes under full-suite runs" — RESOLVED). django-ratelimit
    counts per-IP in the default LocMemCache, which pytest-django does NOT clear
    between tests, and buckets by a wall-clock window. So:
      (a) the autouse reset_cache fixture (tests/conftest.py) gives every test a
          clean counter, so this one starts at 0 regardless of /Equation/ or
          /FitEquation/ requests made elsewhere in the suite, and
      (b) this test freezes django-ratelimit's clock so all 13 POSTs land in ONE
          window and cannot straddle a minute boundary — a straddle resets the
          counter mid-test and under-counts the 13th, which is the original flake
          (it surfaced reliably on the slow macOS CI runner).
    """
    fields = {
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
    url = "/FitEquation__F__/2/Polynomial/2nd Order (Quadratic)/"

    # LongRunningProcessView requires cookie_test to be set on the
    # session (normally set by HomePageView). Seed it so POSTs reach
    # the spawn-dispatch branch and return 302.
    session = client.session
    session["cookie_test"] = 1
    session.save()

    # The autouse reset_cache fixture already zeroed the per-IP counter. Freeze
    # django-ratelimit's window clock so all 13 POSTs share one bucket:
    # django_ratelimit.core._get_window buckets by int(time.time()), so a fixed
    # value keeps them in one window. Patch the name in core's namespace only —
    # zunzun.middleware's own `time` import (used by rate_limit_sleep) is
    # untouched, so the time.sleep patch below still intercepts the limiter's sleep.
    with patch("django_ratelimit.core.time") as ratelimit_clock:
        ratelimit_clock.time.return_value = 1_700_000_000

        # First 12 posts: succeed (302 redirect to /StatusAndResults/),
        # counter 1..12, all at or under the 12/m limit.
        for i in range(12):
            response = client.post(url, data=fields, HTTP_HOST="testserver")
            assert response.status_code == 302, f"Request {i + 1} unexpectedly non-302"

        # 13th post: counter 13 > 12 → rate-limited. Because the view does NOT
        # block (block=False), the request still dispatches (302) but
        # CommonToAllViews' rate_limit_sleep decorator detects request.limited
        # and applies the 5s sleep. We assert the limiter fired by catching it.
        with patch("time.sleep") as mock_sleep:
            response = client.post(url, data=fields, HTTP_HOST="testserver")
            assert any(call.args and call.args[0] >= 5 for call in mock_sleep.call_args_list), (
                "expected request.limited branch to sleep >=5s"
            )
