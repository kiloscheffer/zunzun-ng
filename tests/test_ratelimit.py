"""Rate limit tests.

Asserts that >12 POSTs/minute to a rate-limited view cause the
13th to have request.limited set to True.

Pre-Phase-4 this test FAILS because django_brake is not installed
and the pass-through decorator does not set request.limited.
Post-Phase-4 it PASSES because django-ratelimit sets request.limited.
"""
import pytest


@pytest.mark.django_db
def test_thirteenth_rapid_post_is_rate_limited(client, mocked_process_start):
    """12 POSTs succeed, 13th triggers the rate limiter."""
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

    # First 12 posts: succeed (302 redirect to /StatusAndResults/).
    for i in range(12):
        response = client.post(url, data=fields, HTTP_HOST="testserver")
        assert response.status_code == 302, f"Request {i+1} unexpectedly non-302"

    # 13th post: rate-limited. Because the view does NOT block (uses
    # block=False), the request still gets handled - but CommonToAllViews
    # detects request.limited and applies the 5s sleep then continues.
    # The response status stays 302 (view still dispatched). We test the
    # limiter by asserting the response took noticeably longer OR by
    # patching time.sleep to record its invocations.
    from unittest.mock import patch
    with patch("time.sleep") as mock_sleep:
        response = client.post(url, data=fields, HTTP_HOST="testserver")
        assert any(
            call.args and call.args[0] >= 5
            for call in mock_sleep.call_args_list
        ), "expected request.limited branch to sleep >=5s"
