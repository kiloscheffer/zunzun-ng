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


# ---------------------------------------------------------------------------
# Module-level fake objects for ChildPayload round-trip tests.
# These MUST be at module level (not nested inside test functions) so that
# pickle can resolve them by dotted name. Locally-defined classes raise
# "Can't pickle local object" under HIGHEST_PROTOCOL.
# ---------------------------------------------------------------------------


class _FakeDataObject:
    """Minimal stand-in for the DataObject attr-bag."""
    pass


class _FakeEquation_Spline:
    smoothingFactor = 1.0
    xOrder = 3
    yOrder = 3


class _FakeEquation_Spline3D:
    smoothingFactor = 0.5
    xOrder = 2
    yOrder = 4


class _FakeEquation_UDF:
    userDefinedFunctionText = "a * x + b"


class _FakeEquation_CustomPoly:
    polynomial2DFlags = [True, False, True]


class _FakeEquation_SelectPoly:
    xPolynomialOrder = 3
    yPolynomialOrder = 2


class _FakeEquation_SelectPoly3D:
    xPolynomialOrder = 3
    yPolynomialOrder = 2


class _FakeEquation_Polyfunc:
    polyfunctional2DFlags = [True, True, False]
    polyfunctional3DFlags = [False, True]


class _FakeEquation_Rational:
    rationalNumeratorFlags = [True, False]
    rationalDenominatorFlags = [False, True]


class _FakeEquation_FF:
    """Equation base used by FunctionFinder (sits on dataObject.equation)."""
    pass


class _FakeEquation_FFR:
    """Equation base used by FunctionFinderResults (via boundForm)."""
    pass


class _FakeBoundForm_Spline:
    equation = _FakeEquation_Spline()


class _FakeBoundForm_Spline3D:
    equation = _FakeEquation_Spline3D()


class _FakeBoundForm_UDF:
    equation = _FakeEquation_UDF()


class _FakeBoundForm_CustomPoly:
    equation = _FakeEquation_CustomPoly()


class _FakeBoundForm_SelectPoly:
    equation = _FakeEquation_SelectPoly()


class _FakeBoundForm_SelectPoly3D:
    equation = _FakeEquation_SelectPoly3D()


class _FakeBoundForm_Polyfunc:
    equation = _FakeEquation_Polyfunc()


class _FakeBoundForm_Rational:
    equation = _FakeEquation_Rational()


class _FakeBoundForm_FFR:
    equation = _FakeEquation_FFR()


class _FakeDataObject_FF:
    """DataObject with equation attr for FunctionFinder."""
    equation = _FakeEquation_FF()


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


# ---------------------------------------------------------------------------
# ChildPayload round-trip tests — one per concrete LRP subclass.
# These verify build_child_payload() output survives pickle.HIGHEST_PROTOCOL
# (the protocol used by multiprocessing.Process(spawn)).
# ---------------------------------------------------------------------------


def _base_lrp_attrs(lrp, dimensionality=2):
    """Set the minimum attributes every LRP base class reads in build_child_payload."""
    lrp.session_key_status = "k_status"
    lrp.session_key_data = "k_data"
    lrp.session_key_functionfinder = "k_ff"
    lrp.dimensionality = dimensionality
    lrp.reniceLevel = 10
    lrp.dataObject = None


def test_fit_one_equation_payload_round_trips():
    from zunzun.LongRunningProcess.FitOneEquation import FitOneEquation
    lrp = FitOneEquation()
    _base_lrp_attrs(lrp)
    lrp.boundForm = None  # FittingBaseClass.build_child_payload guards on this
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.lrp_class_path.endswith("FitOneEquation")
    assert clone.session_key_status == "k_status"
    assert clone.dimensionality == 2


def test_fit_spline_payload_round_trips():
    from zunzun.LongRunningProcess.FitSpline import FitSpline
    lrp = FitSpline()
    _base_lrp_attrs(lrp, dimensionality=2)
    lrp.boundForm = _FakeBoundForm_Spline()
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.lrp_class_path.endswith("FitSpline")
    assert clone.extra["xOrder"] == 3
    assert clone.extra["smoothingFactor"] == 1.0
    # yOrder should NOT be present for 2D
    assert "yOrder" not in clone.extra


def test_fit_spline_3d_payload_round_trips():
    """FitSpline adds yOrder only when dimensionality==3."""
    from zunzun.LongRunningProcess.FitSpline import FitSpline
    lrp = FitSpline()
    _base_lrp_attrs(lrp, dimensionality=3)
    lrp.boundForm = _FakeBoundForm_Spline3D()
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.lrp_class_path.endswith("FitSpline")
    assert clone.extra["yOrder"] == 4


def test_fit_user_defined_function_payload_round_trips():
    from zunzun.LongRunningProcess.FitUserDefinedFunction import FitUserDefinedFunction
    lrp = FitUserDefinedFunction()
    _base_lrp_attrs(lrp)
    lrp.boundForm = _FakeBoundForm_UDF()
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.lrp_class_path.endswith("FitUserDefinedFunction")
    assert clone.extra["userDefinedFunctionText"] == "a * x + b"


def test_fit_user_customizable_polynomial_payload_round_trips():
    from zunzun.LongRunningProcess.FitUserCustomizablePolynomial import FitUserCustomizablePolynomial
    lrp = FitUserCustomizablePolynomial()
    _base_lrp_attrs(lrp)
    lrp.boundForm = _FakeBoundForm_CustomPoly()
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.lrp_class_path.endswith("FitUserCustomizablePolynomial")
    assert clone.extra["polynomial2DFlags"] == [True, False, True]


def test_fit_user_selectable_polynomial_payload_round_trips():
    from zunzun.LongRunningProcess.FitUserSelectablePolynomial import FitUserSelectablePolynomial
    lrp = FitUserSelectablePolynomial()
    _base_lrp_attrs(lrp, dimensionality=2)
    lrp.boundForm = _FakeBoundForm_SelectPoly()
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.lrp_class_path.endswith("FitUserSelectablePolynomial")
    assert clone.extra["xPolynomialOrder"] == 3
    assert "yPolynomialOrder" not in clone.extra


def test_fit_user_selectable_polynomial_3d_payload_round_trips():
    """FitUserSelectablePolynomial adds yPolynomialOrder only for 3D."""
    from zunzun.LongRunningProcess.FitUserSelectablePolynomial import FitUserSelectablePolynomial
    lrp = FitUserSelectablePolynomial()
    _base_lrp_attrs(lrp, dimensionality=3)
    lrp.boundForm = _FakeBoundForm_SelectPoly3D()
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.extra["xPolynomialOrder"] == 3
    assert clone.extra["yPolynomialOrder"] == 2


def test_fit_user_selectable_polyfunctional_payload_round_trips():
    from zunzun.LongRunningProcess.FitUserSelectablePolyfunctional import FitUserSelectablePolyfunctional
    lrp = FitUserSelectablePolyfunctional()
    _base_lrp_attrs(lrp)
    lrp.boundForm = _FakeBoundForm_Polyfunc()
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.lrp_class_path.endswith("FitUserSelectablePolyfunctional")
    assert clone.extra["polyfunctional2DFlags"] == [True, True, False]
    assert clone.extra["polyfunctional3DFlags"] == [False, True]


def test_fit_user_selectable_rational_payload_round_trips():
    from zunzun.LongRunningProcess.FitUserSelectableRational import FitUserSelectableRational
    lrp = FitUserSelectableRational()
    _base_lrp_attrs(lrp)
    lrp.boundForm = _FakeBoundForm_Rational()
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.lrp_class_path.endswith("FitUserSelectableRational")
    assert clone.extra["rationalNumeratorFlags"] == [True, False]
    assert clone.extra["rationalDenominatorFlags"] == [False, True]


def test_function_finder_payload_round_trips():
    from zunzun.LongRunningProcess.FunctionFinder import FunctionFinder
    lrp = FunctionFinder()
    _base_lrp_attrs(lrp)
    lrp.dataObject = _FakeDataObject_FF()
    # FunctionFinder.build_child_payload reads self.dataObject.equation
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.lrp_class_path.endswith("FunctionFinder")
    assert clone.session_key_functionfinder == "k_ff"
    # equation should be the _FakeEquation_FF instance we put on dataObject
    assert isinstance(clone.equation, _FakeEquation_FF)


def test_function_finder_results_payload_round_trips():
    from zunzun.LongRunningProcess.FunctionFinderResults import FunctionFinderResults
    lrp = FunctionFinderResults()
    _base_lrp_attrs(lrp)
    lrp.boundForm = _FakeBoundForm_FFR()
    lrp.rank = 5  # set by view dispatcher before build_child_payload
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.lrp_class_path.endswith("FunctionFinderResults")
    assert clone.extra["rank"] == 5


def test_characterize_data_payload_round_trips():
    from zunzun.LongRunningProcess.CharacterizeData import CharacterizeData
    lrp = CharacterizeData()
    _base_lrp_attrs(lrp, dimensionality=1)
    lrp.dataObject = _FakeDataObject()
    lrp.pdfTitleHTML = "Characterize Data 1D"
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.lrp_class_path.endswith("CharacterizeData")
    assert clone.extra["pdfTitleHTML"] == "Characterize Data 1D"
    assert clone.dimensionality == 1


def test_statistical_distributions_payload_round_trips():
    from zunzun.LongRunningProcess.StatisticalDistributions import StatisticalDistributions
    lrp = StatisticalDistributions()
    _base_lrp_attrs(lrp, dimensionality=1)
    lrp.dataObject = _FakeDataObject()
    lrp.pdfTitleHTML = "Statistical Distributions 1D"
    payload = lrp.build_child_payload()
    clone = _roundtrip(payload)
    assert clone.lrp_class_path.endswith("StatisticalDistributions")
    assert clone.extra["pdfTitleHTML"] == "Statistical Distributions 1D"
