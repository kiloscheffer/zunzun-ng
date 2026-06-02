"""Regression test: GET /FitEquation__F__/<dim>/<family>/<name>/?RANK=N must
render the fitting interface form without hitting "session cookie appears to
have expired".

Bug: CreateUnboundInterfaceForm calls LoadItemFromSessionStore which routes to
dispatch_data.load_item(self.status_row_pk, ...). On a GET no dispatch row
exists, so status_row_pk is None -> load_item returns None ->
CreateUnboundInterfaceForm raises "Your browser's session cookie appears to
have expired" -> the view shows "An error occurred while building the form."

Fix: LongRunningProcessView (GET branch) sets
    LRP.status_row_pk = request.session.get("lrp_status_pk")
before calling CreateUnboundInterfaceForm, pointing it at the prior dispatch
(the FunctionFinder ranking) so LoadItemFromSessionStore reads resolve.
"""

import urllib.parse

import pytest

from zunzun.models import LRPDispatchData, LRPStatus


@pytest.mark.django_db
def test_rank_interface_get_renders_without_session_expired_error(client):
    """A GET to the fit interface with ?RANK=1 must render the form, not the
    'session cookie expired' / 'An error occurred while building the form'
    error pages.

    Before the fix: status_row_pk is None on the GET path, so
    CreateUnboundInterfaceForm raises on the functionFinderResultsList load.

    After the fix: status_row_pk is seeded from the session's lrp_status_pk,
    pointing at the prior (ranking) dispatch whose stores hold the data.
    """
    from zunzun.dispatch_data import save_items

    # Simulate a completed FunctionFinder ranking dispatch row.
    ranking = LRPStatus.objects.create(start_time=1.0, state=LRPStatus.State.TERMINAL)
    LRPDispatchData.objects.create(status=ranking)

    # functionFinderResultsList must have >= rank entries with a shape that
    # CreateUnboundInterfaceForm only needs len() and index bounds to validate
    # (it checks len and clamps self.rank, then delegates to
    # SpecificEquationUnboundInterfaceCode which for plain FitOneEquation just
    # calls the base SpecificEquationUnboundInterfaceCode: no indexing into the
    # list). A minimal entry with a list of 12 elements matches the tuple shape
    # FunctionFinder produces.
    fake_results_list = [
        [
            0.001,  # [0] SSQ
            "pyeq3.Models_2D.Polynomial",  # [1] module path
            "Quadratic",  # [2] equation class name
            "Default",  # [3] extended name
            [],  # [4] 2D polyfunctional flags
            [],  # [5] 3D polyfunctional flags
            None,  # [6] xPolynomialOrder
            None,  # [7] yPolynomialOrder
            [],  # [8] rationalNumeratorFlags
            [],  # [9] rationalDenominatorFlags
            "SSQABS",  # [10] fittingTarget
            [1.0, 2.0, 3.0],  # [11] solvedCoefficients
        ],
    ]
    save_items(ranking.pk, "functionfinder", {"functionFinderResultsList": fake_results_list})
    save_items(
        ranking.pk,
        "data",
        {
            "IndependentDataName1": "x",
            "DependentDataName": "y",
            "fittingTarget": "SSQABS",
            "textDataEditor_2D": "1 2\n3 4\n5 6\n",
            "commaConversion": "I",
        },
    )

    # Seed the client session so lrp_status_pk points at the ranking dispatch.
    session = client.session
    session["cookie_test"] = 1
    session["lrp_status_pk"] = ranking.pk
    session.save()

    # Build the URL for 2D Polynomial "2nd Order (Quadratic)" with ?RANK=1.
    eq_name = urllib.parse.quote("2nd Order (Quadratic)")
    url = f"/FitEquation__F__/2/Polynomial/{eq_name}/?RANK=1"

    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode("utf-8", errors="replace")
    assert "session cookie appears to have expired" not in content, (
        "Form render should NOT raise the 'session cookie expired' message. "
        "Check that FIX 1 (LRP.status_row_pk = request.session.get('lrp_status_pk')) "
        "is applied in the GET branch of LongRunningProcessView."
    )
    assert "An error occurred while building the form" not in content, (
        "Form render should NOT show the generic build-error fallback. Check that FIX 1 is applied."
    )
