"""Integration + pin-regression guard for the UDF eval sandbox.

The AST allow-list validator that secures the User-Defined-Function fit path now
lives upstream in pyeq3 (pyeq3/UdfSafety.py), wired into
IModel.ParseAndCompileUserFunctionString. pyeq3's own unittests
(unittests/Test_UserDefinedFunctionSafety.py) cover the validator corpus; these
tests cover (a) that the pinned pyeq3 actually enforces the gate, and (b) that
zunzun's form / view wiring translates a rejected UDF into the right user-facing
response. pyeq3 sanitises fit errors to 1e300, so a malicious UDF can never be
caught via fit output — all assertions are made at the validation gate.
"""

import pytest

# --- Pin-regression guard --------------------------------------------------
# The whole security posture now depends on the pinned pyeq3 self-validating at
# ParseAndCompileUserFunctionString. If a future pin bump lands a pyeq3 without
# UdfSafety (or without the chokepoint wiring), these fail loudly — there is no
# longer a local zunzun/udf_safety.py to fall back on.


# Diverse attack-vector classes the gate must reject AT COMPILE — not just a
# single probe, so a future pin that re-enabled a different node class (a call
# to a builtin, the __import__ RCE) while still blocking attribute access would
# still trip a failure. pyeq3's own unittests own the exhaustive corpus; this is
# the regression sentinel for THIS project's pin.
_MALICIOUS_UDF = [
    "X.__class__",  # attribute access (sandbox-escape traversal entry)
    "__import__('os').system('id')*X",  # the canonical RCE vector
    "eval('1')*X",  # call to a non-arithmetic name + string constant
    "exec('x')*X",  # ditto
]
_BENIGN_UDF = [
    "a + b*X",  # plain linear
    "a*exp(-b*X)+c",  # a numpy function token must still be accepted
]


@pytest.mark.parametrize("expr", _MALICIOUS_UDF)
def test_pinned_pyeq3_rejects_malicious_udf_at_compile(expr):
    import pyeq3

    eq = pyeq3.Models_2D.UserDefinedFunction.UserDefinedFunction("SSQABS", "Default")
    with pytest.raises(pyeq3.UdfSafety.UnsafeUDFError):
        eq.ParseAndCompileUserFunctionString(expr, 2)


@pytest.mark.parametrize("expr", _BENIGN_UDF)
def test_pinned_pyeq3_accepts_benign_udf_at_compile(expr):
    import pyeq3

    eq = pyeq3.Models_2D.UserDefinedFunction.UserDefinedFunction("SSQABS", "Default")
    eq.ParseAndCompileUserFunctionString(expr, 2)  # must not raise


# --- Form-path integration -------------------------------------------------
# A malicious UDF must be rejected during form validation (no spawn), while a
# benign UDF still dispatches. The malicious payload "X.__class__" is harmless
# if it were ever executed (attribute access on a float) but is exactly the
# attribute-traversal class the validator rejects — so the RED run does not
# execute any OS command.

_UDF_BASE_FIELDS = {
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

_UDF_FIT_URL_2D = "/FitEquation__F__/2/UserDefinedFunction/UserDefinedFunction/"


def _seed_cookie_test(client):
    session = client.session
    session["cookie_test"] = 1
    session.save()


@pytest.mark.django_db
def test_malicious_udf_post_is_blocked(client, mocked_process_start):
    _seed_cookie_test(client)
    fields = dict(_UDF_BASE_FIELDS, udfEditor="X.__class__")
    response = client.post(_UDF_FIT_URL_2D, data=fields, HTTP_HOST="testserver")
    # Form rejected -> no spawn, no /StatusAndResults/ redirect.
    assert mocked_process_start.call_count == 0
    assert not (response.status_code == 302 and "/StatusAndResults/" in response.url)
    # Rejection came from our validator, not some unrelated form failure.
    assert b"disallowed construct" in response.content


@pytest.mark.django_db
def test_benign_udf_post_dispatches(client, mocked_process_start):
    _seed_cookie_test(client)
    fields = dict(_UDF_BASE_FIELDS, udfEditor="a + b*X")
    response = client.post(_UDF_FIT_URL_2D, data=fields, HTTP_HOST="testserver")
    assert response.status_code == 302
    assert "/StatusAndResults/" in response.url
    assert mocked_process_start.call_count == 1


# --- EvaluateAtAPoint defense-in-depth -------------------------------------
# The parent gate means a malicious UDF can never reach the session in normal
# flow. This test tampers the dispatch row directly to prove the view
# re-validates and refuses to eval an attribute-traversal payload.


def _seed_udf_dispatch(client, udf_text, dim=2):
    from zunzun.dispatch_data import save_items
    from zunzun.models import LRPStatus

    status = LRPStatus.objects.create(start_time=1.0)
    data = {
        "dimensionality": dim,
        "equationName": "UserDefinedFunction",
        "equationFamilyName": "UserDefinedFunction",
        "solvedCoefficients": [1.0, 1.0],
        "fittingTarget": "SSQABS",
        "udfEditor_" + str(dim) + "D": udf_text,
    }
    save_items(status.pk, "data", data)
    return status.result_token


@pytest.mark.django_db
def test_evaluate_at_point_rejects_tampered_malicious_udf(client):
    # "X.real" is an attribute-traversal expression — the exact construct class
    # the validator categorically rejects (every ast.Attribute is refused,
    # because a builtins-free eval namespace is still escapable via attribute
    # traversal like ().__class__.__bases__[0].__subclasses__()). The classic
    # dunder escapes can't be used as the probe here: pyeq3 sanitises any
    # non-numeric / error result to 1e300 (see CalculateModelPredictions), so
    # "X.__class__" never surfaces as "evaluates to" even unfixed — the test
    # would be a tautology. "X.real" instead yields a finite number (numpy's
    # real part of X), so the UNFIXED view DOES eval it and renders
    # "evaluates to <b>3.0</b>". That makes this a genuine red->green test:
    # the gate must block the eval and return the clean rejection instead.
    token = _seed_udf_dispatch(client, "X.real", dim=2)
    response = client.post(f"/EvaluateAtAPoint/{token}/", data={"x": "3.0"})
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    # The malicious expression was NOT evaluated; the gate returned the clean
    # rejection (distinct from the pre-existing out-of-bounds message).
    assert "evaluates to" not in body
    assert "Invalid data submitted" in body


@pytest.mark.django_db
def test_evaluate_at_point_accepts_benign_udf(client):
    # y = a + b*X with a=1,b=1 at X=3 -> 4; proves the validator does not
    # break legitimate evaluate-at-a-point.
    token = _seed_udf_dispatch(client, "a + b*X", dim=2)
    response = client.post(f"/EvaluateAtAPoint/{token}/", data={"x": "3.0"})
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "evaluates to" in body
