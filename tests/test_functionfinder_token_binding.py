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
