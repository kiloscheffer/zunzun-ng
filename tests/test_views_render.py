"""Direct-render view tests.

Covers the views that call render_to_response (post-refactor: render).
These don't spawn children — they just return HTML. We assert status
code + a marker string that must be in the template output.

Phase 1 calibration notes:
  - /AllEquations/2/Polynomial/ lists "All Standard 2D Equations" — the
    trailing path segment is an all-or-standard flag, not a family name.
  - Invalid-form error template header is "Error In Form" (not "could not").
"""

import pytest


@pytest.mark.django_db
def test_home_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    # Marker that appears on the landing page
    assert b"zunzun" in response.content.lower() or b"curve" in response.content.lower()


@pytest.mark.django_db
def test_all_equations_renders(client):
    response = client.get("/AllEquations/2/Polynomial/")
    assert response.status_code == 200
    assert b"Polynomial" in response.content
    assert b"All Standard 2D Equations" in response.content


@pytest.mark.django_db
def test_invalid_form_post_renders_error_template(client):
    # LongRunningProcessView requires request.session['cookie_test'] to
    # be set — normally done by HomePageView. Seed it directly so the
    # test doesn't depend on cache_page state from prior tests.
    session = client.session
    session["cookie_test"] = 1
    session.save()
    response = client.post(
        "/FitEquation__F__/2/Polynomial/2nd Order (Quadratic)/",
        data={
            "commaConversion": "I",
            "dataNameX": "X",
            "dataNameY": "Y",
            "textDataEditor": "not\nnumbers\nat_all\n",
            "logLinX": "LIN",
            "logLinY": "LIN",
            "logLinZ": "LIN",
            "fittingTarget": "SSQABS",
            "graphSize": "320x240",
            "animationSize": "0x0",
            "scientificNotationX": "AUTO",
            "scientificNotationY": "AUTO",
            "graphScaleRadioButtonX": "0.050",
            "graphScaleRadioButtonY": "0.050",
        },
    )
    # The invalid-form view path doesn't spawn; it renders directly.
    assert response.status_code == 200
    # Error template contains "Error In Form" header
    assert b"Error In Form" in response.content or b"Form error" in response.content
