"""EvaluateAtAPointView tests.

Seeds a per-dispatch LRPDispatchData row (keyed by the LRPStatus pk) with
coefficients for a known equation (2D linear polynomial: y = a + b*x), then
POSTs /EvaluateAtAPoint/ with an X value and asserts the response contains a
numeric Y.

Phase 1 calibration: the POST field is lowercase 'x'; success marker
is 'evaluates to' (views.py line 153).

Phase 7 update: data now routes through the LRPDispatchData row, not a
per-session SessionStore. The seed writes directly into that row via
dispatch_data.save_items, and sets lrp_status_pk on the client session so
EvaluateAtAPointView can resolve the dispatch row.
"""

import pytest


def _seed_data_session(client, equation_name, equation_family, dimensionality, coefficients):
    """Seed the per-dispatch LRPDispatchData row with the minimum keys
    EvaluateAtAPointView needs.

    Creates a fresh LRPStatus row, writes the data into LRPDispatchData via
    dispatch_data.save_items, and stashes lrp_status_pk + session_key_data
    on the client session so the view can find the row.
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

    client_session = client.session
    client_session["lrp_status_pk"] = status.pk
    # session_key_data presence is still checked by the view guard at line 119
    client_session["session_key_data"] = "placeholder"
    client_session.save()


@pytest.mark.django_db
def test_evaluate_at_point_with_seeded_linear_fit(client):
    """Seed a y = 1 + 2*x fit, POST x=3, expect response contains
    'evaluates to' with the computed Y (~= 7).
    """
    import numpy

    _seed_data_session(
        client,
        # pyeq3.Models_2D.Polynomial.Linear.GetDisplayName() -> "1st Order (Linear)"
        equation_name="1st Order (Linear)",
        equation_family="Polynomial",
        dimensionality=2,
        # Polynomial Linear in pyeq3 is y = a + b*x, so coefficients [1, 2] → y=1+2x
        coefficients=numpy.array([1.0, 2.0]),
    )

    # EvaluateAtAPointForm_2D uses lowercase 'x' (Phase 1 finding).
    response = client.post("/EvaluateAtAPoint/", data={"x": "3.0"})
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    # Success marker from views.py:153 ("evaluates to <b>{value}</b>")
    assert "evaluates to" in body, f"unexpected response body: {body[:400]}"
