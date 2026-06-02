"""Regression test: FunctionFinderResults reads the RANKING dispatch's
data/functionfinder store, NOT its own (empty) dispatch row.

The bug: TransferFormDataToDataObject runs in the parent BEFORE the new
status row is written to request.session["lrp_status_pk"] (views.py:756).
Without the fix, status_row_pk is None at read time, so load_item returns
None and the user sees "Your session has expired."

The mechanism: FunctionFinderResults sets self.data_source_pk to the RANKING
dispatch's row pk; the base StatusMonitoredLongRunningProcessPage resolves
reads through _data_read_pk() (data_source_pk when set, else status_row_pk),
so no per-subclass LoadItemFromSessionStore override is needed.
"""

import pytest

from zunzun.models import LRPDispatchData, LRPStatus


@pytest.mark.django_db
def test_functionfinder_results_reads_ranking_dispatch_data():
    """TransferFormDataToDataObject must read from data_source_pk, not
    the (empty/None) status_row_pk of the new FunctionFinderResults dispatch.
    """
    from zunzun.dispatch_data import save_items
    from zunzun.LongRunningProcess.FunctionFinderResults import FunctionFinderResults

    # Simulate a completed RANKING dispatch row with the ranked list + dataset.
    ranking = LRPStatus.objects.create(start_time=1.0, state=LRPStatus.State.TERMINAL)
    LRPDispatchData.objects.create(status=ranking)

    fake_results_list = [
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
        ],
    ]
    save_items(ranking.pk, "functionfinder", {"functionFinderResultsList": fake_results_list})
    save_items(
        ranking.pk,
        "data",
        {
            "IndependentDataName1": "x",
            "IndependentDataName2": "",
            "DependentDataName": "y",
        },
    )

    # Simulate the new (empty) FunctionFinderResults dispatch row — this is
    # what status_row_pk would point to during TransferFormDataToDataObject
    # before the fix.
    new_dispatch = LRPStatus.objects.create(start_time=2.0, state=LRPStatus.State.RUNNING)
    LRPDispatchData.objects.create(status=new_dispatch)

    lrp = FunctionFinderResults()
    lrp.data_source_pk = ranking.pk  # set by the fix (views.py capture)
    lrp.status_row_pk = new_dispatch.pk  # own row — empty, has no functionfinder data

    # Directly test the read path: must return the ranking row's data.
    result = lrp.LoadItemFromSessionStore("functionfinder", "functionFinderResultsList")
    assert result == fake_results_list, (
        "FunctionFinderResults.LoadItemFromSessionStore must read from "
        "data_source_pk, not status_row_pk. Got: %r" % result
    )


@pytest.mark.django_db
def test_functionfinder_results_reads_data_store_from_ranking_row():
    """LoadItemFromSessionStore("data", ...) also reads from data_source_pk."""
    from zunzun.dispatch_data import save_items
    from zunzun.LongRunningProcess.FunctionFinderResults import FunctionFinderResults

    ranking = LRPStatus.objects.create(start_time=1.0, state=LRPStatus.State.TERMINAL)
    LRPDispatchData.objects.create(status=ranking)
    save_items(ranking.pk, "data", {"IndependentDataName1": "pressure"})

    new_dispatch = LRPStatus.objects.create(start_time=2.0, state=LRPStatus.State.RUNNING)
    LRPDispatchData.objects.create(status=new_dispatch)

    lrp = FunctionFinderResults()
    lrp.data_source_pk = ranking.pk
    lrp.status_row_pk = new_dispatch.pk

    result = lrp.LoadItemFromSessionStore("data", "IndependentDataName1")
    assert result == "pressure", (
        "FunctionFinderResults.LoadItemFromSessionStore must read 'data' keys "
        "from data_source_pk. Got: %r" % result
    )


@pytest.mark.django_db
def test_two_concurrent_rankings_resolve_to_distinct_data():
    """Two ranking dispatches in one session get distinct tokens; resolving each
    token reads ITS OWN data, never the other's. Pre-fix the single
    functionfinder_ranking_pk slot collided (BACKLOG #2785)."""
    from zunzun.dispatch_data import save_items
    from zunzun.LongRunningProcess.FunctionFinderResults import FunctionFinderResults
    from zunzun.views import _ranking_pk_from_token

    ranking_a = LRPStatus.objects.create(start_time=1.0, state=LRPStatus.State.TERMINAL)
    LRPDispatchData.objects.create(status=ranking_a)
    ranking_b = LRPStatus.objects.create(start_time=2.0, state=LRPStatus.State.TERMINAL)
    LRPDispatchData.objects.create(status=ranking_b)
    assert ranking_a.result_token != ranking_b.result_token

    save_items(ranking_a.pk, "functionfinder", {"functionFinderResultsList": ["A_LIST"]})
    save_items(ranking_b.pk, "functionfinder", {"functionFinderResultsList": ["B_LIST"]})

    # Each results page resolves its ranking from its own token, in any order.
    lrp_b = FunctionFinderResults()
    lrp_b.data_source_pk = _ranking_pk_from_token(ranking_b.result_token)
    lrp_a = FunctionFinderResults()
    lrp_a.data_source_pk = _ranking_pk_from_token(ranking_a.result_token)

    assert lrp_a.LoadItemFromSessionStore("functionfinder", "functionFinderResultsList") == [
        "A_LIST"
    ]
    assert lrp_b.LoadItemFromSessionStore("functionfinder", "functionFinderResultsList") == [
        "B_LIST"
    ]
