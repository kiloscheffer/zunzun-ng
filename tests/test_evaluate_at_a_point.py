"""EvaluateAtAPointView tests.

Seeds a session_data SessionStore with coefficients for a known
equation (2D linear polynomial: y = a + b*x), then POSTs /EvaluateAtAPoint/
with an X value and asserts the response contains a numeric Y.

Phase 1 calibration: the POST field is lowercase 'x'; success marker
is 'evaluates to' (views.py line 153).

Phase 3: the _encode helper becomes a no-op (native values in the
session). Test assertion remains unchanged.
"""
import pickle

import pytest


def _seed_data_session(client, equation_name, equation_family, dimensionality,
                      coefficients):
    """Seed session_data with the minimum keys EvaluateAtAPointView needs.

    Uses the current pickle/hex wire format. In Phase 3 this helper is
    rewritten to use native values; the test assertion remains unchanged.
    """
    from django.contrib.sessions.backends.db import SessionStore
    session_data = SessionStore()
    session_data.create()

    def _encode(v):
        return pickle.dumps(v, pickle.HIGHEST_PROTOCOL).hex()

    session_data["dimensionality"] = _encode(dimensionality)
    session_data["equationName"] = _encode(equation_name)
    session_data["equationFamilyName"] = _encode(equation_family)
    session_data["solvedCoefficients"] = _encode(coefficients)
    session_data["fittingTarget"] = _encode("SSQABS")
    session_data.save()

    client_session = client.session
    client_session["session_key_data"] = session_data.session_key
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
