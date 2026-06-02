"""Tests for FunctionFinder ranking identity via result_token (BACKLOG #2785, #2817)."""

import pytest

from zunzun.models import LRPDispatchData, LRPStatus


@pytest.mark.django_db
def test_ranking_pk_from_token_resolves_independent_of_session():
    """The token→pk resolver finds the ranking row regardless of any session;
    that session-independence is what makes a shared link work cross-session."""
    from zunzun.views import _ranking_pk_from_token

    ranking = LRPStatus.objects.create(start_time=1.0, state=LRPStatus.State.TERMINAL)

    assert _ranking_pk_from_token(ranking.result_token) == ranking.pk
    assert _ranking_pk_from_token("") is None
    assert _ranking_pk_from_token("does-not-exist") is None
    assert _ranking_pk_from_token(None) is None


@pytest.mark.django_db
def test_functionfinder_terminal_redirect_embeds_ranking_token(tmp_path, monkeypatch):
    """FunctionFinder's terminal redirect must carry &ranking=<own token> so the
    results page (and shared links) can resolve the ranking by token."""
    import settings
    from zunzun.LongRunningProcess.FunctionFinder import FunctionFinder

    monkeypatch.setattr(settings, "TEMP_FILES_DIR", str(tmp_path))

    # A real ranking row (process_id set so the defensive get_status guard passes)
    # plus its data row, since RenderOutputHTML writes the functionfinder/data blobs.
    row = LRPStatus.objects.create(start_time=1.0, process_id=4321)
    LRPDispatchData.objects.create(status=row)

    lrp = FunctionFinder()
    lrp.status_row_pk = row.pk
    lrp.result_token = row.result_token
    lrp.functionFinderResultsList = []

    class _DO:
        dimensionality = 2
        textDataEditor = "1 1\n2 2\n"
        weightedFittingChoice = "N"
        fittingTarget = "SSQABS"
        DependentDataArray = []
        IndependentDataArray = []
        logLinX = "lin"
        logLinY = "lin"

    lrp.dataObject = _DO()

    lrp.RenderOutputHTMLToAFileAndSetStatusRedirect()

    reloaded = LRPStatus.objects.get(pk=row.pk)
    assert f"ranking={row.result_token}" in reloaded.redirect_to_results, (
        f"redirect must embed the ranking token; got {reloaded.redirect_to_results!r}"
    )
    assert "/FunctionFinderResults/2/?RANK=1" in reloaded.redirect_to_results


@pytest.mark.django_db
def test_functionfinder_results_links_carry_ranking_token(tmp_path, monkeypatch):
    """The rendered results page's navigation links must carry &ranking=<token>
    so a recipient (any session) can navigate Prev/Next/'Go to this equation'."""
    import settings
    from zunzun.LongRunningProcess.FunctionFinderResults import FunctionFinderResults

    monkeypatch.setattr(settings, "TEMP_FILES_DIR", str(tmp_path))

    results_row = LRPStatus.objects.create(start_time=2.0, process_id=999)
    LRPDispatchData.objects.create(status=results_row)

    lrp = FunctionFinderResults()
    lrp.status_row_pk = results_row.pk
    lrp.ranking_token = "TESTRANKINGTOKEN"
    lrp.dimensionality = 2
    lrp.previousSelectorRank = 0
    lrp.nextSelectorRank = 41
    lrp.RelativeErrorPlotsFlag = False
    lrp.equationDataForDjangoTemplate = []

    class _DO:
        dimensionality = 2
        uniqueString = "zun_0000_00000000"

    lrp.dataObject = _DO()

    lrp.RenderOutputHTMLToAFileAndSetStatusRedirect()

    reloaded = LRPStatus.objects.get(pk=results_row.pk)
    with open(reloaded.redirect_to_results, encoding="utf-8") as f:
        html = f.read()
    # Next link is rendered (nextSelectorRank=41) and must carry the token.
    assert "RANK=41&ranking=TESTRANKINGTOKEN" in html, "Next-set link must carry the ranking token"


@pytest.mark.django_db
def test_functionfinder_results_payload_round_trips_ranking_token():
    """build/apply_child_payload must carry ranking_token to the child."""
    from zunzun.LongRunningProcess.FunctionFinderResults import FunctionFinderResults

    lrp = FunctionFinderResults()
    lrp.status_row_pk = 0
    lrp.dimensionality = 2
    lrp.ranking_status_pk = 7
    lrp.ranking_token = "TOK"
    lrp.rank = 1
    payload = lrp.build_child_payload()
    assert payload.extra["ranking_token"] == "TOK"

    fresh = FunctionFinderResults()
    fresh.apply_child_payload(payload)
    assert fresh.ranking_token == "TOK"


@pytest.mark.django_db
def test_functionfinder_results_get_resolves_by_token_cross_session(client, mocked_process_start):
    """A FunctionFinderResults GET with ?ranking=<token> and NO prior session
    state must resolve the ranking by token, set cookie_test, and dispatch a
    render child (302 to /StatusAndResults/<pk>/) — proving cross-session
    sharing (#2817). It must NOT return the 'expired'/'requires cookie' page."""
    from unittest import mock

    from zunzun.dispatch_data import save_items

    ranking = LRPStatus.objects.create(start_time=1.0, state=LRPStatus.State.TERMINAL)
    LRPDispatchData.objects.create(status=ranking)
    save_items(
        ranking.pk,
        "functionfinder",
        {
            "functionFinderResultsList": [
                [
                    0.001,
                    "pyeq3.Models_2D.Polynomial",
                    "Quadratic",
                    "Default",
                    [],
                    [],
                    None,
                    None,
                    [],
                    [],
                    "SSQABS",
                    [1.0, 2.0, 3.0],
                ]
            ]
        },
    )
    save_items(
        ranking.pk,
        "data",
        {
            "IndependentDataName1": "x",
            "IndependentDataName2": "",
            "DependentDataName": "y",
            "commaConversion": "I",
            "textDataEditor": "1 2\n3 4\n5 6\n",
            "weightedFittingChoice": "N",
            "fittingTarget": "SSQABS",
            "DependentDataArray": [],
            "IndependentDataArray": [],
            "logLinX": "lin",
            "logLinY": "lin",
        },
    )

    # Fresh client: brand-new session, no cookie_test, no functionfinder_ranking_pk.
    assert client.session.get("cookie_test") is None  # cold session: no cookie_test yet
    url = f"/FunctionFinderResults/2/?RANK=1&ranking={ranking.result_token}"
    with mock.patch("settings.MAX_CONCURRENT_FITS_PER_SESSION", 1, create=True):
        with mock.patch("settings.MAX_CONCURRENT_FITS_PER_IP", 99, create=True):
            resp = client.get(url, HTTP_HOST="testserver")

    assert resp.status_code == 302, (
        f"expected dispatch redirect, got {resp.status_code}: "
        f"{resp.content[:200] if resp.status_code == 200 else ''!r}"
    )
    assert "/StatusAndResults/" in resp["Location"]
    assert client.session.get("cookie_test") == 1, "cookie_test must be set for a token-bearer"


@pytest.mark.django_db
def test_functionfinder_results_get_expired_token_short_circuits(client):
    """A FunctionFinderResults GET with a missing/invalid token returns a clean
    expired message without spawning a child."""
    resp = client.get("/FunctionFinderResults/2/?RANK=1&ranking=nope")
    assert resp.status_code == 200
    assert "expired" in resp.content.decode("utf-8", errors="replace").lower()


@pytest.mark.django_db
def test_results_view_appends_token_to_legacy_functionfinder_redirect(client):
    """Deploy-cutover survival (Codex PR #37): a FunctionFinder ranking row
    written BEFORE token-binding has a tokenless redirect_to_results
    ('/FunctionFinderResults/<dim>/?RANK=1&unused=...'). ResultsView must append
    the row's own token so the now-token-resolved dispatch can still find the
    (retained) ranking instead of reading it as expired."""
    row = LRPStatus.objects.create(
        start_time=1.0,
        state=LRPStatus.State.TERMINAL,
        redirect_to_results="/FunctionFinderResults/2/?RANK=1&unused=123.0",
    )
    resp = client.get(f"/Results/{row.result_token}/")
    assert resp.status_code == 302
    assert "/FunctionFinderResults/2/?RANK=1" in resp["Location"]
    assert f"ranking={row.result_token}" in resp["Location"]


@pytest.mark.django_db
def test_rank_interface_get_without_token_shows_clean_expired_message(client):
    """Deploy-cutover (Codex PR #37, 2nd P2): a "Go to this equation" link baked
    into a FunctionFinderResults page rendered BEFORE token-binding has ?RANK= but
    no &ranking=. After deploy, clicking it hits the interface GET with an
    unresolvable token; rather than the opaque "error building the form" fallback,
    show a clear, actionable "expired, re-run" message (parity with the Prev/Next
    short-circuit)."""
    import urllib.parse

    session = client.session
    session["cookie_test"] = 1
    session.save()

    eq_name = urllib.parse.quote("2nd Order (Quadratic)")
    resp = client.get(f"/FitEquation__F__/2/Polynomial/{eq_name}/?RANK=1")
    assert resp.status_code == 200
    body = resp.content.decode("utf-8", errors="replace").lower()
    assert "expired" in body
    assert "error occurred while building the form" not in body


@pytest.mark.django_db
def test_results_view_does_not_double_append_ranking_token(client):
    """A current (post-token-binding) FunctionFinder redirect already carries
    &ranking=; ResultsView must NOT append a second one."""
    row = LRPStatus.objects.create(
        start_time=1.0,
        state=LRPStatus.State.TERMINAL,
        redirect_to_results="/FunctionFinderResults/2/?RANK=1&ranking=existingtok&unused=1.0",
    )
    resp = client.get(f"/Results/{row.result_token}/")
    assert resp.status_code == 302
    assert resp["Location"].count("ranking=") == 1
    assert "ranking=existingtok" in resp["Location"]
