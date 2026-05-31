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

from zunzun.LongRunningProcess.FittingBaseClass import FittingBaseClass


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


def test_polynomial_customization_3d_data_flag_and_initial_value():
    html = render_to_string(
        "zunzun/divs/polynomial_customization_div.html",
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
    result = FittingBaseClass._build_3d_color_list(
        _fake_3d_self(), lambda i, j: [i, j] in flags
    )
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
    result = FittingBaseClass._build_3d_color_list(
        _fake_3d_self(), lambda i, j: [i, j] in flags
    )
    assert result == [
        (True, 0, 0, "Offset", ""),   # offset branch
        (True, 0, 1, "", "Y"),        # Y-only branch
        (True, 1, 0, "X", ""),        # X-only branch
        (False, 1, 1, "X", "Y"),      # general branch, not selected
    ]
