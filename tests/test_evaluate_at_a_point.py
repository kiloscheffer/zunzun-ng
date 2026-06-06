"""EvaluateAtAPointView tests.

Seeds a per-dispatch LRPDispatchData row (keyed by the LRPStatus pk) with
coefficients for a known equation (2D linear polynomial: y = a + b*x), then
POSTs /EvaluateAtAPoint/<token>/ with an X value and asserts the response
contains a numeric Y.

Phase 1 calibration: the POST field is lowercase 'x'; success marker
is 'evaluates to' (views.py line 153).

Phase 10 update: EvaluateAtAPointView now reads the dispatch by the
result_token in the URL, not the session.  The seed returns the token so
the test can build the correct URL.  lrp_status_pk / session_key_data
are no longer set (the view no longer reads them).
"""

import pytest


def _seed_data_session(
    client, equation_name, equation_family, dimensionality, coefficients, extra=None
):
    """Seed the per-dispatch LRPDispatchData row with the minimum keys
    EvaluateAtAPointView needs.

    Creates a fresh LRPStatus row (with a result_token), writes the data into
    LRPDispatchData via dispatch_data.save_items, and returns the result_token
    so the caller can build the token-addressed URL.

    `extra`, if given, is merged into the data dict — used to seed
    equation-specific keys (e.g. a spline's degrees).
    """
    from zunzun.dispatch_data import save_items
    from zunzun.models import LRPStatus

    status = LRPStatus.objects.create(start_time=1.0)
    data = {
        "dimensionality": dimensionality,
        "equationName": equation_name,
        "equationFamilyName": equation_family,
        # numpy array → plain list for JSON-serialisable storage
        "solvedCoefficients": list(coefficients),
        "fittingTarget": "SSQABS",
    }
    if extra:
        data.update(extra)
    save_items(status.pk, "data", data)

    return status.result_token


@pytest.mark.django_db
def test_evaluate_at_point_with_seeded_linear_fit(client):
    """Seed a y = 1 + 2*x fit, POST x=3, expect response contains
    'evaluates to' with the computed Y (~= 7).
    """
    import numpy

    token = _seed_data_session(
        client,
        # pyeq3.Models_2D.Polynomial.Linear.GetDisplayName() -> "1st Order (Linear)"
        equation_name="1st Order (Linear)",
        equation_family="Polynomial",
        dimensionality=2,
        # Polynomial Linear in pyeq3 is y = a + b*x, so coefficients [1, 2] → y=1+2x
        coefficients=numpy.array([1.0, 2.0]),
    )

    # EvaluateAtAPointForm_2D uses lowercase 'x' (Phase 1 finding).
    response = client.post(f"/EvaluateAtAPoint/{token}/", data={"x": "3.0"})
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    # Success marker from views.py ("evaluates to <b>{value}</b>")
    assert "evaluates to" in body, f"unexpected response body: {body[:400]}"


@pytest.mark.django_db
def test_two_token_evaluate_isolation(client):
    """B2: Two separately-seeded dispatches with different coefficients must
    return different evaluation values at the same x — proof that the
    token-addressed per-dispatch data rows are isolated from each other.

    Polynomial Linear in pyeq3 is y = a + b*x:
      dispatch A: a=1,  b=2  -> y(3) = 1  + 2*3  = 7
      dispatch B: a=10, b=2  -> y(3) = 10 + 2*3  = 16
    """
    import numpy

    # Seed two independent dispatches.
    token_a = _seed_data_session(
        client,
        equation_name="1st Order (Linear)",
        equation_family="Polynomial",
        dimensionality=2,
        coefficients=numpy.array([1.0, 2.0]),  # y = 1 + 2x
    )
    token_b = _seed_data_session(
        client,
        equation_name="1st Order (Linear)",
        equation_family="Polynomial",
        dimensionality=2,
        coefficients=numpy.array([10.0, 2.0]),  # y = 10 + 2x
    )

    # Same x, different tokens -> different results.
    resp_a = client.post(f"/EvaluateAtAPoint/{token_a}/", data={"x": "3.0"})
    resp_b = client.post(f"/EvaluateAtAPoint/{token_b}/", data={"x": "3.0"})

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200

    body_a = resp_a.content.decode("utf-8")
    body_b = resp_b.content.decode("utf-8")

    assert "evaluates to" in body_a, f"token A unexpected body: {body_a[:400]}"
    assert "evaluates to" in body_b, f"token B unexpected body: {body_b[:400]}"

    # The two evaluations must yield different numeric results (7.0 vs 16.0).
    assert body_a != body_b, (
        f"Both tokens returned the same body — dispatch data is not isolated:\n"
        f"  token A body: {body_a[:200]}\n"
        f"  token B body: {body_b[:200]}"
    )


@pytest.mark.django_db
def test_evaluate_at_point_with_seeded_3d_spline(client):
    """Seed a fitted 3D spline and POST (x, y); expect 'evaluates to' with the
    value scipy's own .ev yields.

    Regression guard for the 3D-spline reconstruction in EvaluateAtAPointView.
    pyeq3's SolveUsingSpline sets solvedCoefficients = scipySpline.tck, which
    for a SmoothBivariateSpline is the 3-tuple (tx, ty, c) — the degrees
    (kx, ky) live in scipySpline.degrees, NOT in .tck. The view must read the
    degrees from a separately-saved key, not from tck[3]/tck[4] (which raise
    IndexError: tuple index out of range — the bug this test pins). The 2D
    spline path is unaffected because UnivariateSpline._eval_args bundles the
    degree at index 2.
    """
    import re

    import numpy
    import scipy.interpolate

    # 25-point smooth surface, cubic-by-cubic spline.
    xs = numpy.array([0, 1, 2, 3, 4] * 5, dtype=float)
    ys = numpy.repeat(numpy.array([0, 1, 2, 3, 4], dtype=float), 5)
    zs = xs + 2 * ys + 0.1 * xs * ys
    spline = scipy.interpolate.SmoothBivariateSpline(xs, ys, zs, kx=3, ky=3)

    x0, y0 = 2.5, 1.5
    expected = float(spline.ev(numpy.array([x0]), numpy.array([y0]))[0])

    token = _seed_data_session(
        client,
        # GetEquationFromNameAndFamily matches a 3D spline on ("Spline", "Spline").
        equation_name="Spline",
        equation_family="Spline",
        dimensionality=3,
        # pyeq3 SolveUsingSpline sets solvedCoefficients = scipySpline.tck.
        coefficients=list(spline.tck),
        # The fix persists the spline degrees separately (FitSpline saves them).
        extra={"splineDegrees": list(spline.degrees)},
    )

    response = client.post(f"/EvaluateAtAPoint/{token}/", data={"x": str(x0), "y": str(y0)})
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "evaluates to" in body, f"unexpected response body: {body[:400]}"

    match = re.search(r"<b>(.*?)</b>", body)
    assert match, f"no numeric value in response: {body[:400]}"
    assert float(match.group(1)) == pytest.approx(expected, rel=1e-9)


@pytest.mark.django_db
def test_evaluate_3d_spline_missing_degrees_fails_gracefully(client):
    """A 3D-spline dispatch row written BEFORE 'splineDegrees' was persisted
    (solvedCoefficients present, no degrees) must return a graceful message,
    not crash with an unhandled TypeError/500 when the view unpacks the
    missing degrees.
    """
    import numpy
    import scipy.interpolate

    xs = numpy.array([0, 1, 2, 3, 4] * 5, dtype=float)
    ys = numpy.repeat(numpy.array([0, 1, 2, 3, 4], dtype=float), 5)
    zs = xs + 2 * ys + 0.1 * xs * ys
    spline = scipy.interpolate.SmoothBivariateSpline(xs, ys, zs, kx=3, ky=3)

    # No 'splineDegrees' seeded — emulates a pre-fix dispatch row.
    token = _seed_data_session(
        client,
        equation_name="Spline",
        equation_family="Spline",
        dimensionality=3,
        coefficients=list(spline.tck),
    )

    response = client.post(f"/EvaluateAtAPoint/{token}/", data={"x": "2.5", "y": "1.5"})
    assert response.status_code == 200
    assert "expired" in response.content.decode("utf-8")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "dimensionality, equation_attrs, expected_degrees",
    [
        # 3D: scipy's BivariateSpline.tck carries no degrees, so FitSpline must
        # persist them under 'splineDegrees' for the view to reconstruct with.
        (3, {"xOrder": 3, "yOrder": 2}, [3, 2]),
        # 2D: UnivariateSpline._eval_args already bundles the degree at index 2,
        # so the extra key must NOT be written (the read side never looks for it).
        (2, {"xOrder": 3}, None),
    ],
    ids=["3D-persists-degrees", "2D-omits-degrees"],
)
def test_fitspline_persists_spline_degrees_only_for_3d(
    dimensionality, equation_attrs, expected_degrees
):
    """FitSpline.SaveSpecificDataToSessionStore persists the spline degrees
    under 'splineDegrees' for a 3D fit and omits the key for 2D.

    The seeded-read test above supplies 'splineDegrees' itself, so it only
    exercises the READ side (EvaluateAtAPointView). This pins the WRITE side:
    scipy's BivariateSpline.tck (stored as solvedCoefficients) carries no
    degrees, so FitSpline must save them under the exact key the view reads —
    otherwise the two halves of the contract can silently drift apart.
    """
    import types

    import numpy

    from zunzun.dispatch_data import load_item
    from zunzun.LongRunningProcess.FitSpline import FitSpline
    from zunzun.models import LRPStatus

    status = LRPStatus.objects.create(start_time=1.0)
    fit = FitSpline()
    fit.status_row_pk = status.pk
    fit.dimensionality = dimensionality
    fit.inEquationName = "Spline"
    fit.inEquationFamilyName = "Spline"
    # solvedCoefficients value is irrelevant to the degree-persistence contract;
    # a placeholder tck suffices. xOrder/yOrder are the spline degrees the
    # solver used (== scipySpline.degrees).
    fit.dataObject = types.SimpleNamespace(
        equation=types.SimpleNamespace(
            solvedCoefficients=(numpy.array([0.0]), numpy.array([1.0]), numpy.array([2.0])),
            **equation_attrs,
        )
    )

    fit.SaveSpecificDataToSessionStore()

    assert load_item(status.pk, "data", "splineDegrees") == expected_degrees
    assert load_item(status.pk, "data", "dimensionality") == dimensionality
