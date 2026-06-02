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
