"""Regression coverage for the matrix-selector (coefficient picker) modernization.

The polyfunctional / polynomial-customization / polyrational selection UIs moved
their cell selection state off an inline ``style="background-color:rgb(...)"``
attribute (read/written by legacy Netscape/IE DOM JS) and onto a ``selected``
CSS class. The Python builders now emit a ``selected`` bool as the first tuple
element of each ``*ColorList`` instead of an rgb string; the templates map that
bool to ``class="pick math selected"``.

These tests pin two things the migration must never regress:

1. The bool -> class mapping is NOT inverted. ``True`` (the old white
   ``rgb(255,255,255)``) means SELECTED; ``False`` (old lightgray
   ``rgb(211,211,211)``) means unselected. The original BACKLOG recipe had this
   backwards, which would have silently flipped every coefficient selection.
2. No inline picker ``background-color:rgb(...)`` survives — the cell's
   appearance is fully class-driven.

The direct ``render_to_string`` tests exercise the bool->class logic without a
live equation/session; the view-integration test proves the full URL -> view ->
template path still renders the picker class-driven. (The full page legitimately
contains the substring ``background-color`` from the unrelated
``estimated_coefficient_entry_div.html``; only ``background-color:rgb(`` is the
old picker pattern, so that is what the integration test guards against.)
"""

import types

import pytest
from django.template.loader import render_to_string
from django.test import RequestFactory

from zunzun.LongRunningProcess.FittingBaseClass import FittingBaseClass
from zunzun.LongRunningProcess.FitUserCustomizablePolynomial import (
    FitUserCustomizablePolynomial,
)
from zunzun.LongRunningProcess.FitUserSelectablePolyfunctional import (
    FitUserSelectablePolyfunctional,
)


def _polyfunctional_2d(selected_first):
    return render_to_string(
        "zunzun/divs/polyfunctional_selection_div.html",
        {
            "dimensionality": "2",
            "equationHTML": "",
            "Polyfun2DColorList": [
                (selected_first, 0, "X"),
                (not selected_first, 1, "X^2"),
            ],
        },
    )


def test_polyfunctional_selected_bool_maps_to_class():
    """A True entry renders the .selected class; a False entry does not."""
    html = _polyfunctional_2d(selected_first=True)
    # CPX0 is selected (True) -> carries the class; CPX1 (False) does not.
    assert "class=\"pick math selected\" id='CPX0'" in html
    assert "class=\"pick math\" id='CPX1'" in html


def test_polyfunctional_unselected_has_no_selected_class():
    """Flipping the bool flips which cell carries .selected (not inverted)."""
    html = _polyfunctional_2d(selected_first=False)
    assert "class=\"pick math\" id='CPX0'" in html
    assert "class=\"pick math selected\" id='CPX1'" in html


def test_polyfunctional_has_no_inline_background_color():
    html = _polyfunctional_2d(selected_first=True)
    assert "background-color" not in html


def test_polynomial_customization_selected_bool_maps_to_class():
    html = render_to_string(
        "zunzun/divs/polynomial_customization_div.html",
        {
            "dimensionality": "2",
            "equationHTML": "",
            "Polynomial2DColorList": [(True, 0, "1"), (False, 1, "X")],
        },
    )
    assert "class=\"pick math selected\" id='CPX0'" in html
    assert "class=\"pick math\" id='CPX1'" in html
    assert "background-color" not in html


def test_polyrational_selected_bool_and_offset_map_to_class():
    html = render_to_string(
        "zunzun/divs/polyrational_selection_div.html",
        {
            "dimensionality": "2",
            "equationHTML": "",
            "Polyrat2DNumeratorColorList": [(True, 0, "X")],
            "Polyrat2DDenominatorColorList": [(False, 0, "X")],
            "offsetSelected": True,
        },
    )
    assert "class=\"pick math selected\" id='CPX_N0'" in html
    assert "class=\"pick math\" id='CPX_D0'" in html
    # The standalone offset cell honors the offsetSelected bool.
    assert "class=\"pick math selected\" id='CPX_OFFSET'" in html
    assert "background-color" not in html


def test_polyfunctional_2d_data_flag_and_initial_value():
    """Each cell names its hidden field via data-flag; the hidden input's
    initial value mirrors the selected bool (so rank pre-fill survives
    without readPolyFlags)."""
    html = _polyfunctional_2d(selected_first=True)
    assert 'data-flag="polyFunctional_X0"' in html
    assert 'data-flag="polyFunctional_X1"' in html
    assert 'name="polyFunctional_X0" value="True"' in html
    assert 'name="polyFunctional_X1" value="False"' in html


def test_polynomial_customization_2d_data_flag_and_initial_value():
    html = render_to_string(
        "zunzun/divs/polynomial_customization_div.html",
        {
            "dimensionality": "2",
            "equationHTML": "",
            "Polynomial2DColorList": [(True, 0, "1"), (False, 1, "X")],
        },
    )
    assert 'data-flag="polyFunctional_X0"' in html
    assert 'data-flag="polyFunctional_X1"' in html
    assert 'name="polyFunctional_X0" value="True"' in html
    assert 'name="polyFunctional_X1" value="False"' in html


def test_polyrational_2d_data_flag_and_initial_value():
    html = render_to_string(
        "zunzun/divs/polyrational_selection_div.html",
        {
            "dimensionality": "2",
            "equationHTML": "",
            "Polyrat2DNumeratorColorList": [(True, 0, "X")],
            "Polyrat2DDenominatorColorList": [(False, 0, "X")],
            "offsetSelected": True,
        },
    )
    assert 'data-flag="polyRational_X_N0"' in html
    assert 'data-flag="polyRational_X_D0"' in html
    assert 'data-flag="polyRational_OFFSET"' in html
    assert 'name="polyRational_X_N0" value="True"' in html
    assert 'name="polyRational_X_D0" value="False"' in html
    assert 'name="polyRational_OFFSET" value="True"' in html


def test_polyfunctional_3d_data_flag_and_initial_value():
    html = render_to_string(
        "zunzun/divs/polyfunctional_selection_div.html",
        {
            "dimensionality": "3",
            "equationHTML": "",
            "maxPolyfunctionalListIndex": 1,
            "Polyfun3DColorList": [
                (True, 0, 0, "Offset", ""),
                (False, 0, 1, "", "Y"),
                (False, 1, 0, "X", ""),
                (False, 1, 1, "X", "Y"),
            ],
        },
    )
    assert 'data-flag="polyFunctional_X0Y0"' in html
    assert 'data-flag="polyFunctional_X1Y1"' in html
    assert 'name="polyFunctional_X0Y0" value="True"' in html
    assert 'name="polyFunctional_X1Y1" value="False"' in html


@pytest.mark.django_db
def test_polyfunctional_interface_renders_class_driven(client):
    """Full URL -> view -> template path renders the picker, class-driven.

    Scopes the no-inline-style check to ``background-color:rgb(`` — the exact
    old picker pattern — so it does not false-positive on the unrelated
    estimated-coefficient div's ``background-color:" + bg`` JS string.
    """
    client.get("/")  # bootstrap session
    session = client.session
    session["cookie_test"] = 1
    session.save()
    response = client.get("/Equation/2/Polyfunctional/User-Selectable Polyfunctional/")
    assert response.status_code == 200
    body = response.content.decode("utf-8", "replace")
    # Cells render and keep their click handler...
    assert 'class="pick math' in body
    assert "cT(this.id" in body
    # ...but no inline picker background-color survives.
    assert "background-color:rgb(" not in body
    # readPolyFlags was deleted; submit is now a plain <input type="submit">.
    assert "readPolyFlags" not in body
    assert '<input type="submit" value="Submit">' in body


@pytest.mark.django_db
def test_customizable_polynomial_interface_renders_class_driven(client):
    """FitUserCustomizablePolynomial's 2D no-rank caller renders the picker
    class-driven via the Polynomial2DColorList key — the second
    _build_2d_color_list call site (the polyfunctional test above covers the
    first). Without this, FitUserCustomizablePolynomial had no picker-render
    coverage at all, so a wiring break (wrong dict key, dropped color list)
    in that subclass would ship silently."""
    client.get("/")  # bootstrap session
    session = client.session
    session["cookie_test"] = 1
    session.save()
    response = client.get("/Equation/2/Polynomial/User-Customizable Polynomial/")
    assert response.status_code == 200
    body = response.content.decode("utf-8", "replace")
    # Right equation dispatched + rendered (proves this subclass's picker)...
    assert "User-Customizable Polynomial" in body
    # ...class-driven cells, no legacy inline picker background survives.
    assert 'class="pick math' in body
    assert "background-color:rgb(" not in body


class _HtmlStub:
    def __init__(self, html):
        self.HTML = html


def _fake_3d_self():
    # _build_3d_color_list reads only self.X3DList / self.Y3DList and each
    # item's .HTML. Index 0 of each axis is the offset position; its .HTML is
    # never read (the (0,0) cell is hardcoded "Offset").
    return types.SimpleNamespace(
        X3DList=[_HtmlStub("x0"), _HtmlStub("X")],
        Y3DList=[_HtmlStub("y0"), _HtmlStub("Y")],
    )


def test_build_3d_color_list_no_rank_all_unselected():
    result = FittingBaseClass._build_3d_color_list(_fake_3d_self(), lambda i, j: False)
    assert result == [
        (False, 0, 0, "Offset", ""),
        (False, 0, 1, "", "Y"),
        (False, 1, 0, "X", ""),
        (False, 1, 1, "X", "Y"),
    ]


def test_build_3d_color_list_rank_predicate_marks_selected_cells():
    flags = [[1, 1]]
    result = FittingBaseClass._build_3d_color_list(_fake_3d_self(), lambda i, j: [i, j] in flags)
    assert result == [
        (False, 0, 0, "Offset", ""),
        (False, 0, 1, "", "Y"),
        (False, 1, 0, "X", ""),
        (True, 1, 1, "X", "Y"),
    ]


def test_build_3d_color_list_predicate_selects_offset_and_axis_cells():
    # selected=True must thread through every positional branch, not just the
    # general (i>0, j>0) cell.
    flags = [[0, 0], [1, 0], [0, 1]]
    result = FittingBaseClass._build_3d_color_list(_fake_3d_self(), lambda i, j: [i, j] in flags)
    assert result == [
        (True, 0, 0, "Offset", ""),  # offset branch
        (True, 0, 1, "", "Y"),  # Y-only branch
        (True, 1, 0, "X", ""),  # X-only branch
        (False, 1, 1, "X", "Y"),  # general branch, not selected
    ]


def _fake_2d_self():
    # _build_2d_color_list reads only self.X2DList and each item's .HTML.
    # Unlike 3D, 2D has no offset special-case: every cell's .HTML is read,
    # including index 0.
    return types.SimpleNamespace(
        X2DList=[_HtmlStub("X"), _HtmlStub("X^2"), _HtmlStub("X^3")],
    )


def test_build_2d_color_list_no_rank_all_unselected():
    result = FittingBaseClass._build_2d_color_list(_fake_2d_self(), lambda i: False)
    assert result == [
        (False, 0, "X"),
        (False, 1, "X^2"),
        (False, 2, "X^3"),
    ]


def test_build_2d_color_list_rank_predicate_marks_selected_cells():
    # Mirrors the production caller's `i in flags` rank pre-fill predicate.
    flags = [1]
    result = FittingBaseClass._build_2d_color_list(_fake_2d_self(), lambda i: i in flags)
    assert result == [
        (False, 0, "X"),
        (True, 1, "X^2"),
        (False, 2, "X^3"),
    ]


def test_polyrational_3d_data_flag_and_initial_value():
    """Polyrational 3D uses the polyfunctional matrix names (polyFunctional_XiYj);
    data-flag and hidden-input initial value must be present and correct."""
    html = render_to_string(
        "zunzun/divs/polyrational_selection_div.html",
        {
            "dimensionality": "3",
            "equationHTML": "",
            "maxPolyfunctionalListIndex": 1,
            "Polyfun3DColorList": [
                (True, 0, 0, "Offset", ""),
                (False, 0, 1, "", "Y"),
                (False, 1, 0, "X", ""),
                (False, 1, 1, "X", "Y"),
            ],
        },
    )
    assert 'data-flag="polyFunctional_X0Y0"' in html
    assert 'data-flag="polyFunctional_X1Y1"' in html
    assert 'name="polyFunctional_X0Y0" value="True"' in html
    assert 'name="polyFunctional_X1Y1" value="False"' in html


class _FakeBoundField:
    required = False


class _FakeBoundForm:
    """Minimal stand-in for a bound Equation_2D / Equation_3D form: supports
    item access (each access returns a throwaway field, matching how form[name]
    works) and carries the .equation the parser writes flags onto."""

    def __init__(self):
        self.equation = types.SimpleNamespace()

    def __getitem__(self, key):
        return _FakeBoundField()


def test_bound_interface_3d_maps_posted_flag_to_equation_flags():
    """SpecificEquationBoundInterfaceCode correctly maps a POSTed
    polyFunctional_XiYj=True into equation.polyfunctional3DFlags — no fit
    spawned, no real form, no DB."""
    lrp = FitUserSelectablePolyfunctional()
    lrp.dimensionality = 3
    lrp.boundForm = _FakeBoundForm()
    # Build the full 3D grid POST, all False except the ASYMMETRIC cell (i=1,
    # j=0). Asymmetric on purpose: a symmetric cell like (1, 1) could not
    # distinguish a correct append([i, j]) from a transposed append([j, i]).
    post = {}
    for i in range(len(lrp.X3DList)):
        for j in range(len(lrp.Y3DList)):
            post[f"polyFunctional_X{i}Y{j}"] = "True" if (i, j) == (1, 0) else "False"
    request = RequestFactory().post("/", data=post)
    lrp.SpecificEquationBoundInterfaceCode(request)
    # [[1, 0]], not [[0, 1]] — pins the (i, j) ordering against transposition.
    assert lrp.boundForm.equation.polyfunctional3DFlags == [[1, 0]]
    # The 2D list must be initialized to [] even on the 3D path —
    # build_child_payload carries both across the spawn boundary.
    assert lrp.boundForm.equation.polyfunctional2DFlags == []


# --- New shared picker helpers (FittingBaseClass) ---------------------------
# These call self._build_{2,3}d_color_list, so the test "self" must be a real
# subclass instance (which has those methods + the X2DList/X3DList/Y3DList that
# __init__ populates), not a SimpleNamespace stub.


def test_assign_2d_picker_color_list_no_rank_selects_nothing():
    lrp = FitUserSelectablePolyfunctional()
    lrp.rank = None
    lrp.equation = types.SimpleNamespace()
    lrp.dictionaryToReturn = {}
    lrp._assign_2d_picker_color_list("Polynomial2DColorList", "polynomial2DFlags")
    color_list = lrp.dictionaryToReturn["Polynomial2DColorList"]
    assert len(color_list) == len(lrp.X2DList)
    assert all(entry[0] is False for entry in color_list)


def test_assign_2d_picker_color_list_rank_prefills_index_4_and_sets_equation_attr():
    lrp = FitUserSelectablePolyfunctional()
    lrp.rank = 1
    lrp.functionFinderResultsList = [[None, None, None, None, [1]]]  # index [4] -> 2D flags
    lrp.equation = types.SimpleNamespace()
    lrp.dictionaryToReturn = {}
    lrp._assign_2d_picker_color_list("Polyfun2DColorList", "polyfunctional2DFlags")
    assert lrp.equation.polyfunctional2DFlags == [1]
    color_list = lrp.dictionaryToReturn["Polyfun2DColorList"]
    assert color_list[1][0] is True  # cell 1 pre-selected
    assert color_list[0][0] is False


def test_assign_3d_picker_color_list_no_rank_selects_nothing():
    lrp = FitUserSelectablePolyfunctional()
    lrp.rank = None
    lrp.equation = types.SimpleNamespace()
    lrp.dictionaryToReturn = {}
    lrp._assign_3d_picker_color_list("Polyfun3DColorList", "polyfunctional3DFlags")
    color_list = lrp.dictionaryToReturn["Polyfun3DColorList"]
    assert len(color_list) == len(lrp.X3DList) * len(lrp.Y3DList)
    assert all(entry[0] is False for entry in color_list)


def test_assign_3d_picker_color_list_rank_prefills_index_5_and_sets_equation_attr():
    lrp = FitUserSelectablePolyfunctional()
    lrp.rank = 1
    lrp.functionFinderResultsList = [[None, None, None, None, None, [[1, 0]]]]  # index [5] -> 3D
    lrp.equation = types.SimpleNamespace()
    lrp.dictionaryToReturn = {}
    lrp._assign_3d_picker_color_list("Polyfun3DColorList", "polyfunctional3DFlags")
    assert lrp.equation.polyfunctional3DFlags == [[1, 0]]
    color_list = lrp.dictionaryToReturn["Polyfun3DColorList"]
    selected = [(e[1], e[2]) for e in color_list if e[0] is True]
    assert selected == [(1, 0)]  # asymmetric cell pins (i, j) ordering


def test_collect_2d_picker_flags_maps_posted_true_to_indices():
    lrp = FitUserSelectablePolyfunctional()
    lrp.boundForm = _FakeBoundForm()
    post = {
        "polyFunctional_X" + str(i): ("True" if i == 1 else "False")
        for i in range(len(lrp.X2DList))
    }
    request = RequestFactory().post("/", data=post)
    lrp._collect_2d_picker_flags(request, "polynomial2DFlags")
    assert lrp.boundForm.equation.polynomial2DFlags == [1]


def test_collect_3d_picker_flags_maps_posted_true_to_pairs():
    lrp = FitUserSelectablePolyfunctional()
    lrp.boundForm = _FakeBoundForm()
    post = {}
    for i in range(len(lrp.X3DList)):
        for j in range(len(lrp.Y3DList)):
            post[f"polyFunctional_X{i}Y{j}"] = "True" if (i, j) == (1, 0) else "False"
    request = RequestFactory().post("/", data=post)
    lrp._collect_3d_picker_flags(request, "polyfunctional3DFlags")
    assert lrp.boundForm.equation.polyfunctional3DFlags == [[1, 0]]


def test_customizable_polynomial_bound_2d_maps_posted_flag_to_equation_flags():
    """FitUserCustomizablePolynomial's 2D POST path maps a posted
    polyFunctional_Xi=True into equation.polynomial2DFlags. Characterizes the
    behavior preserved by the helper delegation (no fit, no real form, no DB)."""
    lrp = FitUserCustomizablePolynomial()
    lrp.dimensionality = 2
    lrp.boundForm = _FakeBoundForm()
    post = {
        "polyFunctional_X" + str(i): ("True" if i == 2 else "False")
        for i in range(len(lrp.X2DList))
    }
    request = RequestFactory().post("/", data=post)
    lrp.SpecificEquationBoundInterfaceCode(request)
    assert lrp.boundForm.equation.polynomial2DFlags == [2]


def test_customizable_polynomial_is_2d_only_in_pyeq3():
    """The dead 3D picker branches were removed on this invariant: pyeq3 exposes
    'User-Customizable Polynomial' only in Models_2D, never Models_3D. So
    GetEquationFromNameAndFamily returns a real equation in 2D and None in 3D.
    If a future pyeq3 ever ships a 3D customizable polynomial, this test fails —
    re-add 3D handling to FitUserCustomizablePolynomial and its template."""
    lrp = FitUserCustomizablePolynomial()

    lrp.dimensionality = 2
    eq_2d = lrp.GetEquationFromNameAndFamily(
        "User-Customizable Polynomial", "Polynomial", checkForSplinesAndUserDefinedFunctionsFlag=1
    )
    assert eq_2d is not None
    assert eq_2d.userCustomizablePolynomialFlag is True

    lrp.dimensionality = 3
    eq_3d = lrp.GetEquationFromNameAndFamily(
        "User-Customizable Polynomial", "Polynomial", checkForSplinesAndUserDefinedFunctionsFlag=1
    )
    assert eq_3d is None


def test_bound_interface_2d_maps_posted_flag_to_equation_flags():
    """SpecificEquationBoundInterfaceCode 2D path maps a POSTed
    polyFunctional_Xi=True into equation.polyfunctional2DFlags AND leaves the
    inactive polyfunctional3DFlags as [] (build_child_payload carries both)."""
    lrp = FitUserSelectablePolyfunctional()
    lrp.dimensionality = 2
    lrp.boundForm = _FakeBoundForm()
    post = {
        "polyFunctional_X" + str(i): ("True" if i == 1 else "False")
        for i in range(len(lrp.X2DList))
    }
    request = RequestFactory().post("/", data=post)
    lrp.SpecificEquationBoundInterfaceCode(request)
    assert lrp.boundForm.equation.polyfunctional2DFlags == [1]
    assert lrp.boundForm.equation.polyfunctional3DFlags == []
