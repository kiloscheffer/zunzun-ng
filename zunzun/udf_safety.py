"""AST allow-list sandbox for User-Defined-Function expression text.

The UDF fit path eval()s user-submitted expressions. pyeq3's only gate
(ProcessAndValidateFunctionString) is cosmetic and does not reject dangerous
names, so an anonymous POST could achieve remote code execution in the web
process (e.g. ``__import__('os').system('id')*X``). This module re-parses the
expression and walks it against a strict allow-list, rejecting everything
outside pure arithmetic over X/Y, coefficient names, and the numpy tokens
pyeq3 injects into safe_dict.

Rejecting every ``ast.Attribute`` and ``ast.Subscript`` node is the security
core: a builtins-free eval namespace is still escapable via attribute
traversal (``().__class__.__bases__[0].__subclasses__()``); removing ``.`` and
``[]`` at the grammar level kills that entire family. Underscore-led names are
rejected as belt-and-suspenders against dunders.

Call this on the *transformed* string (post
ProcessAndValidateFunctionString, brackets already ``[]``->``()``), AFTER
pyeq3's compile step (which is non-executing and populates the coefficient
designators) and BEFORE any eval. See
docs/superpowers/specs/2026-06-08-udf-eval-sandbox-design.md.
"""

import ast


class UnsafeUDFError(ValueError):
    """A UDF expression contained a construct outside the safe arithmetic grammar."""


# Expression-level nodes that pure arithmetic over named values may use.
_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Name,
    ast.Constant,
    ast.Load,
    # binary operators
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.FloorDiv,
    # unary operators
    ast.UAdd,
    ast.USub,
)


def validate_udf_expression(expression_text, allowed_names):
    """Raise UnsafeUDFError unless expression_text is safe arithmetic over
    allowed_names. allowed_names is a set of permitted bare identifiers
    (X/Y, coefficient designators, numpy tokens)."""
    try:
        tree = ast.parse(expression_text, mode="eval")
    except SyntaxError as exc:
        raise UnsafeUDFError(f"could not parse expression ({exc})")

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            raise UnsafeUDFError("attribute access is not allowed")
        if isinstance(node, ast.Subscript):
            raise UnsafeUDFError("subscripting is not allowed")
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafeUDFError(f"{type(node).__name__} is not allowed")

        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, complex)) or isinstance(node.value, bool):
                raise UnsafeUDFError("only numeric constants are allowed")

        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise UnsafeUDFError(f"name {node.id!r} is not allowed")
            if node.id not in allowed_names:
                raise UnsafeUDFError(f"unknown name {node.id!r}")

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise UnsafeUDFError("only calls to named functions are allowed")
            if node.keywords:
                raise UnsafeUDFError("keyword arguments are not allowed")
            if any(isinstance(arg, ast.Starred) for arg in node.args):
                raise UnsafeUDFError("starred arguments are not allowed")


def collect_allowed_names(equation, dim):
    """Build the permitted-name set for a UDF equation: X (+ Y for 3D),
    the parsed coefficient designators, and every numpy token pyeq3 lists in
    functionDictionary / constantsDictionary."""
    names = {"X"}
    if dim == 3:
        names.add("Y")
    names.update(getattr(equation, "_coefficientDesignators", []))
    for tokens in equation.functionDictionary.values():
        names.update(tokens)
    for tokens in equation.constantsDictionary.values():
        names.update(tokens)
    return names
