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


def _seed_data_session(client, equation_name, equation_family, dimensionality, coefficients):
    """Seed the per-dispatch LRPDispatchData row with the minimum keys
    EvaluateAtAPointView needs.

    Creates a fresh LRPStatus row (with a result_token), writes the data into
    LRPDispatchData via dispatch_data.save_items, and returns the result_token
    so the caller can build the token-addressed URL.
    """
    from zunzun.dispatch_data import save_items
    from zunzun.models import LRPStatus

    status = LRPStatus.objects.create(start_time=1.0)
    save_items(
        status.pk,
        "data",
        {
            "dimensionality": dimensionality,
            "equationName": equation_name,
            "equationFamilyName": equation_family,
            # numpy array → plain list for JSON-serialisable storage
            "solvedCoefficients": list(coefficients),
            "fittingTarget": "SSQABS",
        },
    )

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
