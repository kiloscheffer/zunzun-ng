"""Verify pyeq3 equations and LRP subclasses survive pickle round-trip.

This test is the empirical check for the risk flagged in
docs/superpowers/specs/2026-04-17-cross-platform-design.md §4.4
before Phase 2 rewires LongRunningProcessView to spawn.

We test pickling under the spawn protocol specifically (highest
pickle protocol) because that's what multiprocessing.Process(spawn)
uses internally.
"""
import pickle

import pytest

import pyeq3


def _roundtrip(obj):
    """Pickle with HIGHEST_PROTOCOL (matches multiprocessing.spawn)."""
    data = pickle.dumps(obj, pickle.HIGHEST_PROTOCOL)
    return pickle.loads(data)


def test_pyeq3_polynomial_equation_pickles():
    # pyeq3.Models_2D.Polynomial has no class named 'Polynomial';
    # the concrete classes are Quadratic, Linear, Cubic, etc.
    eq = pyeq3.Models_2D.Polynomial.Quadratic("SSQABS", "Default")
    clone = _roundtrip(eq)
    assert clone.GetDisplayName() == eq.GetDisplayName()
    assert clone.__class__.__name__ == eq.__class__.__name__


def test_pyeq3_spline_equation_pickles():
    eq = pyeq3.Models_2D.Spline.Spline("SSQABS", "Default")
    clone = _roundtrip(eq)
    assert clone.__class__.__name__ == eq.__class__.__name__


def test_pyeq3_user_defined_function_pickles():
    eq = pyeq3.Models_2D.UserDefinedFunction.UserDefinedFunction("SSQABS", "Default")
    # These typically have a parsed function body; ensure the class itself
    # survives even if the parsed state needs re-parsing in the child
    clone = _roundtrip(eq)
    assert clone.__class__.__name__ == eq.__class__.__name__


def test_pyeq3_3d_equation_pickles():
    # pyeq3.Models_3D.Polynomial has no class named 'Polynomial';
    # the concrete classes are FullQuadratic, FullCubic, Linear, etc.
    eq = pyeq3.Models_3D.Polynomial.FullQuadratic("SSQABS", "Default")
    clone = _roundtrip(eq)
    assert clone.GetDisplayName() == eq.GetDisplayName()


def test_lrp_instance_pickles_minimally():
    """Even the bare LRP instance (no form data yet) should pickle.

    Note: `dimensionality` is NOT set in __init__; it is injected by the
    view dispatcher at ``LRP.dimensionality = int(inDimensionality)``
    after the LRP is constructed.  We verify the class pickles intact and
    that persistent __init__ state (e.g. inEquationName) round-trips.
    """
    from zunzun.LongRunningProcess import FitOneEquation
    lrp = FitOneEquation.FitOneEquation()
    clone = _roundtrip(lrp)
    assert clone.__class__.__name__ == "FitOneEquation"
    # inEquationName is set in StatusMonitoredLongRunningProcessPage.__init__
    assert clone.inEquationName == lrp.inEquationName
