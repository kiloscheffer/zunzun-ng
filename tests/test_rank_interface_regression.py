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
raises "session cookie appears to have expired". The initial fix introduced a
dedicated session key "functionfinder_ranking_pk"; that slot is now fully retired.

Fix: LongRunningProcessView (GET branch, ?RANK present) resolves the ranking via
    LRP.data_source_pk = _ranking_pk_from_token(request.GET.get("ranking"))
The ranking identity rides in the URL (?ranking=<token>) rather than a session
slot, making the pre-fill cross-session: any browser that receives the link can
open the fitting interface form for the correct dataset without needing a matching
session cookie.
"""

import urllib.parse

import pytest

from zunzun.models import LRPDispatchData, LRPStatus


@pytest.mark.django_db
def test_rank_interface_get_renders_without_session_expired_error(client):
    """A GET to the fit interface with ?RANK=1&ranking=<token> must render the
    form, not the 'session cookie expired' / 'An error occurred while building
    the form' error pages.

    This test verifies that the ranking identity rides in the URL token
    (?ranking=<token>), resolved via _ranking_pk_from_token, NOT a session slot.
    The session is seeded with only cookie_test (no functionfinder_ranking_pk).
    If the view still read functionfinder_ranking_pk from the session, it would
    find None and raise "session cookie appears to have expired" — the test
    would fail, proving the token path is actually used.
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

    # Seed only cookie_test; the ranking identity now rides in the URL, NOT a
    # session slot. Deliberately do NOT set functionfinder_ranking_pk — if the
    # view still read it, this test would fail, proving the token path works.
    session = client.session
    session["cookie_test"] = 1
    session.save()

    eq_name = urllib.parse.quote("2nd Order (Quadratic)")
    url = f"/FitEquation__F__/2/Polynomial/{eq_name}/?RANK=1&ranking={ranking.result_token}"

    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode("utf-8", errors="replace")
    assert "session cookie appears to have expired" not in content, (
        "Form render should NOT raise the 'session cookie expired' message. "
        "Check that the ?RANK= GET path resolves via _ranking_pk_from_token "
        "(?ranking=<token> URL param) in LongRunningProcessView."
    )
    assert "An error occurred while building the form" not in content, (
        "Form render should NOT show the generic build-error fallback. "
        "Check that the ?RANK= GET path resolves ranking by URL token."
    )
