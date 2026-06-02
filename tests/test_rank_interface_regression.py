"""Regression test: GET /FitEquation__F__/<dim>/<family>/<name>/?RANK=N must
render the fitting interface form without hitting "session cookie appears to
have expired".

Bug (original): CreateUnboundInterfaceForm calls LoadItemFromSessionStore which
routes to dispatch_data.load_item(self.status_row_pk, ...). On a GET no dispatch
row exists, so status_row_pk is None -> load_item returns None ->
CreateUnboundInterfaceForm raises "Your browser's session cookie appears to
have expired" -> the view shows "An error occurred while building the form."

Bug (P1 / PR #36): After the FIRST FunctionFinderResults page renders, the session
key lrp_status_pk is overwritten with that result page's OWN (data-less) row pk.
If the ?RANK= GET then reads lrp_status_pk it finds an empty store and still
raises "session cookie appears to have expired". The fix introduces a dedicated,
stable session key "functionfinder_ranking_pk" that is set ONLY on the ranking
dispatch (FunctionFinder__ path) and is NOT overwritten by follow-up dispatches.

Fix: LongRunningProcessView (GET branch, ?RANK present) sets
    LRP.status_row_pk = request.session.get("functionfinder_ranking_pk")
before calling CreateUnboundInterfaceForm, pointing it at the stable ranking
dispatch so LoadItemFromSessionStore reads resolve even after follow-up
FunctionFinderResults pages have moved lrp_status_pk.
"""

import urllib.parse

import pytest

from zunzun.models import LRPDispatchData, LRPStatus


@pytest.mark.django_db
def test_rank_interface_get_renders_without_session_expired_error(client):
    """A GET to the fit interface with ?RANK=1 must render the form, not the
    'session cookie expired' / 'An error occurred while building the form'
    error pages.

    This test verifies the P1 fix (PR #36): the stable session key
    "functionfinder_ranking_pk" is used for ?RANK= GETs, NOT the mutable
    "lrp_status_pk". The test deliberately sets lrp_status_pk to a DIFFERENT,
    EMPTY row (simulating what happens after a FunctionFinderResults page has
    rendered and clobbered lrp_status_pk) while functionfinder_ranking_pk
    still points at the real ranking dispatch. If the view reads lrp_status_pk
    instead, it finds an empty store and raises "session cookie appears to have
    expired" — the test would fail, proving the bug was present before this fix.
    """
    from zunzun.dispatch_data import save_items

    # Simulate a completed FunctionFinder ranking dispatch row with real data.
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

    # Simulate a FunctionFinderResults follow-up dispatch that has clobbered
    # lrp_status_pk with its own (data-less) row. This is the state that would
    # cause the bug: if the view reads lrp_status_pk it finds an empty store.
    empty_results_row = LRPStatus.objects.create(start_time=1.0, state=LRPStatus.State.TERMINAL)
    LRPDispatchData.objects.create(status=empty_results_row)
    # NOTE: no save_items for empty_results_row — it has no functionfinder data.

    # Seed the client session:
    # - functionfinder_ranking_pk -> the real ranking row (stable, not clobbered)
    # - lrp_status_pk -> the empty results row (simulating post-results-page state)
    session = client.session
    session["cookie_test"] = 1
    session["functionfinder_ranking_pk"] = ranking.pk
    session["lrp_status_pk"] = empty_results_row.pk  # clobbered — must NOT be used for ?RANK=
    session.save()

    # Build the URL for 2D Polynomial "2nd Order (Quadratic)" with ?RANK=1.
    eq_name = urllib.parse.quote("2nd Order (Quadratic)")
    url = f"/FitEquation__F__/2/Polynomial/{eq_name}/?RANK=1"

    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode("utf-8", errors="replace")
    assert "session cookie appears to have expired" not in content, (
        "Form render should NOT raise the 'session cookie expired' message. "
        "Check that the ?RANK= GET path reads 'functionfinder_ranking_pk' "
        "(not the mutable 'lrp_status_pk') in LongRunningProcessView."
    )
    assert "An error occurred while building the form" not in content, (
        "Form render should NOT show the generic build-error fallback. "
        "Check that the ?RANK= GET path reads 'functionfinder_ranking_pk'."
    )
