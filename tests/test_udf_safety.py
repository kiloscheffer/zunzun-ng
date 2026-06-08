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


@pytest.mark.django_db
def test_benign_udf_post_dispatches(client, mocked_process_start):
    _seed_cookie_test(client)
    fields = dict(_UDF_BASE_FIELDS, udfEditor="a + b*X")
    response = client.post(_UDF_FIT_URL_2D, data=fields, HTTP_HOST="testserver")
    assert response.status_code == 302
    assert "/StatusAndResults/" in response.url
    assert mocked_process_start.call_count == 1
