"""Unit corpus for the UDF AST sandbox (zunzun/udf_safety.py).

The validator is the primary security net for the User-Defined-Function fit
path: it must reject anything outside pure arithmetic over X/Y, coefficient
names, and the numpy tokens pyeq3 injects into safe_dict. These tests assert
at the validator gate directly — pyeq3 sanitises fit errors to 1e300, so a
malicious UDF can never be caught via fit output.
"""

import pytest

from zunzun.udf_safety import UnsafeUDFError, validate_udf_expression

# X, Y, a couple of coefficients, and the numpy tokens a real UDF may use.
ALLOWED = {"X", "Y", "a", "b", "c", "exp", "sin", "sqrt", "fabs", "arctan2", "pi", "e"}

MALICIOUS = [
    "__import__('os').system('id')*X",  # builtins via dunder name
    "().__class__.__bases__[0].__subclasses__()",  # attribute-traversal escape
    "X.__class__",  # attribute access
    "(1).__class__",  # attribute on a literal
    "eval('1')+X",  # eval call
    "exec('x')+X",  # exec call
    "open('f') and X",  # file access + BoolOp
    "globals() and X",  # builtins call
    "'os' and X",  # string constant payload
    "().__class__.__bases__[0]",  # subscript escape
    "exp(x=1)+X",  # keyword-arg call
    "foo*X",  # unknown bare name
    "[X for a in X]",  # comprehension
    "(lambda: X)()",  # lambda
    "(a := X)",  # walrus / NamedExpr
    "f'{X}'",  # f-string (JoinedStr)
    "t'{X}'",  # t-string / TemplateStr (py3.14)
    "sin(X for a in X)",  # generator expression
    "X if a else b",  # ternary IfExp
    "a < X < b",  # chained compare
    "exp(**a)",  # dict-unpack into call
    "sin(open('x'))",  # dangerous inner call
    "sin(X).real",  # attribute on a call result
]

BENIGN = [
    "a + b*X",
    "a*exp(-b*X)+c",
    "sin(X)+sqrt(fabs(X))",
    "a*X**2 + b*X + c",
    "a*X + b*Y",
    "a*X + pi",
    "arctan2(X, a)",
]


@pytest.mark.parametrize("expr", MALICIOUS)
def test_malicious_udf_rejected(expr):
    with pytest.raises(UnsafeUDFError):
        validate_udf_expression(expr, ALLOWED)


@pytest.mark.parametrize("expr", BENIGN)
def test_benign_udf_accepted(expr):
    # Must not raise.
    validate_udf_expression(expr, ALLOWED)


def test_syntax_error_is_unsafe_not_crash():
    with pytest.raises(UnsafeUDFError):
        validate_udf_expression("a + *X", ALLOWED)


def test_collect_allowed_names_from_real_2d_udf():
    import pyeq3
    from zunzun.udf_safety import collect_allowed_names

    eq = pyeq3.Models_2D.UserDefinedFunction.UserDefinedFunction("SSQABS", "Default")
    eq.ParseAndCompileUserFunctionString("a + b*X", 2)
    names = collect_allowed_names(eq, 2)
    assert "X" in names
    assert "Y" not in names
    assert {"a", "b"} <= names
    assert {"exp", "sin", "sqrt", "pi", "e"} <= names


def test_collect_allowed_names_3d_includes_Y():
    import pyeq3
    from zunzun.udf_safety import collect_allowed_names

    eq = pyeq3.Models_3D.UserDefinedFunction.UserDefinedFunction("SSQABS", "Default")
    eq.ParseAndCompileUserFunctionString("a*X + b*Y", 3)
    names = collect_allowed_names(eq, 3)
    assert {"X", "Y", "a", "b"} <= names


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
