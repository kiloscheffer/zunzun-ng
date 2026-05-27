"""Spawn dispatch tests.

POSTs to fit URLs are expected to:
  1. validate the form,
  2. build a ChildPayload,
  3. call multiprocessing.get_context("spawn").Process(...).start(),
  4. redirect to /StatusAndResults/.

multiprocessing.context.SpawnProcess.start is patched to a no-op via
the mocked_process_start fixture, so no actual child is spawned.

The view builds its redirect using request.META['HTTP_HOST']; under
the Django test client this resolves to 'testserver' so the redirect
target is 'http://testserver/StatusAndResults/'.
"""
import pytest

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
    # Successful dispatch returns a redirect to the status page.
    assert response.status_code == 302
    assert response.url.endswith("/StatusAndResults/")
    # The Process.start mock was called exactly once.
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
    assert response.url.endswith("/StatusAndResults/")
    assert mocked_process_start.call_count == 1


@pytest.mark.django_db
def test_status_view_renders_without_session_keys(client):
    """GET /StatusAndResults/ with no session keys should not crash."""
    response = client.get("/StatusAndResults/")
    # The view should render or return a sensible 200/4xx — not 500.
    assert response.status_code in (200, 302, 400, 404)
