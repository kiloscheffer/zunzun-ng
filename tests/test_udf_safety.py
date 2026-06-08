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
