"""Spawn dispatch tests.

POSTs to fit URLs are expected to:
  1. validate the form,
  2. build a ChildPayload,
  3. call multiprocessing.get_context("spawn").Process(...).start(),
  4. redirect to /StatusAndResults/<pk>/.

multiprocessing.context.SpawnProcess.start is patched to a no-op via
the mocked_process_start fixture, so no actual child is spawned.

The view returns a host-relative redirect ('/StatusAndResults/<pk>/'),
so the redirect target is independent of the Host header and preserves
the request scheme behind a TLS-terminating proxy.
"""

import re

import pytest

# A host-relative redirect to the pk-addressed status page: leading slash
# (so no scheme/host), trailing pk. The leading "^/" is what asserts the
# redirect is relative rather than an absolute http://host/... URL.
_STATUS_REDIRECT = re.compile(r"^/StatusAndResults/\d+/$")

_VALID_POLY_FIELDS = {
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


def _seed_cookie_test(client):
    """LongRunningProcessView rejects POSTs that don't have cookie_test
    set on the session — normally set by HomePageView. Seed it directly
    so tests don't depend on HomePageView's cache_page state.
    """
    session = client.session
    session["cookie_test"] = 1
    session.save()


@pytest.mark.django_db
def test_fit_post_dispatches_and_redirects(client, mocked_process_start):
    _seed_cookie_test(client)
    response = client.post(
        "/FitEquation__F__/2/Polynomial/2nd Order (Quadratic)/",
        data=_VALID_POLY_FIELDS,
        HTTP_HOST="testserver",
    )
    # Successful dispatch returns a host-relative redirect to the
    # pk-addressed status page — no scheme, no host (see test_fit_redirect_
    # is_relative_and_ignores_host for why that matters).
    assert response.status_code == 302
    assert "://" not in response.url, (
        f"Redirect must be host-relative, got absolute URL: {response.url}"
    )
    assert _STATUS_REDIRECT.match(response.url), (
        f"Expected /StatusAndResults/<pk>/ redirect, got: {response.url}"
    )
    # The Process.start mock was called exactly once.
    assert mocked_process_start.call_count == 1


@pytest.mark.django_db
def test_fit_redirect_is_relative_and_ignores_host(client, mocked_process_start):
    """The post-dispatch redirect must NOT be built from the Host header.

    With ALLOWED_HOSTS = ["*"], a client-supplied Host header is attacker-
    controlled; echoing it into an absolute redirect makes the response
    host-header sensitive. A host-relative redirect also preserves the
    request scheme (https) behind a TLS-terminating proxy instead of
    forcing http://. Spoof a hostile Host and assert it never leaks into
    the Location.
    """
    _seed_cookie_test(client)
    response = client.post(
        "/FitEquation__F__/2/Polynomial/2nd Order (Quadratic)/",
        data=_VALID_POLY_FIELDS,
        HTTP_HOST="evil.example.com",
    )
    assert response.status_code == 302
    assert "evil.example.com" not in response.url, (
        f"Host header leaked into redirect: {response.url}"
    )
    assert _STATUS_REDIRECT.match(response.url), (
        f"Expected host-relative /StatusAndResults/<pk>/ redirect, got: {response.url}"
    )
    assert mocked_process_start.call_count == 1


@pytest.mark.django_db
def test_characterize_post_dispatches(client, mocked_process_start):
    _seed_cookie_test(client)
    response = client.post(
        "/CharacterizeData/2/",
        data=_VALID_POLY_FIELDS,
        HTTP_HOST="testserver",
    )
    assert response.status_code == 302
    assert "://" not in response.url, (
        f"Redirect must be host-relative, got absolute URL: {response.url}"
    )
    assert _STATUS_REDIRECT.match(response.url), (
        f"Expected /StatusAndResults/<pk>/ redirect, got: {response.url}"
    )
    assert mocked_process_start.call_count == 1


@pytest.mark.django_db
def test_status_redirect_view_renders_without_session_keys(client):
    """GET /StatusAndResults/ (bare) with no active row returns the
    'No fit in progress' page (200) — StatusRedirectView's no-row branch."""
    response = client.get("/StatusAndResults/")
    assert response.status_code == 200
    assert b"No fit in progress" in response.content
