"""Regression test: FunctionFinderResults reads the RANKING dispatch's
data/functionfinder store, NOT its own (empty) dispatch row.

The bug: TransferFormDataToDataObject runs in the parent BEFORE the new
status row is written to request.session["lrp_status_pk"] (views.py:756).
Without the fix, status_row_pk is None at read time, so load_item returns
None and the user sees "Your session has expired."

The fix: FunctionFinderResults overrides LoadItemFromSessionStore to read
from self.ranking_status_pk (captured from the session pointer that still
points at the RANKING dispatch when views.py:724 runs).
"""

import pytest

from zunzun.models import LRPDispatchData, LRPStatus


@pytest.mark.django_db
def test_functionfinder_results_reads_ranking_dispatch_data():
    """TransferFormDataToDataObject must read from ranking_status_pk, not
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
    lrp.ranking_status_pk = ranking.pk  # set by the fix (views.py capture)
    lrp.status_row_pk = new_dispatch.pk  # own row — empty, has no functionfinder data

    # Directly test the read path: must return the ranking row's data.
    result = lrp.LoadItemFromSessionStore("functionfinder", "functionFinderResultsList")
    assert result == fake_results_list, (
        "FunctionFinderResults.LoadItemFromSessionStore must read from "
        "ranking_status_pk, not status_row_pk. Got: %r" % result
    )


@pytest.mark.django_db
def test_functionfinder_results_reads_data_store_from_ranking_row():
    """LoadItemFromSessionStore("data", ...) also reads from ranking_status_pk."""
    from zunzun.dispatch_data import save_items
    from zunzun.LongRunningProcess.FunctionFinderResults import FunctionFinderResults

    ranking = LRPStatus.objects.create(start_time=1.0, state=LRPStatus.State.TERMINAL)
    LRPDispatchData.objects.create(status=ranking)
    save_items(ranking.pk, "data", {"IndependentDataName1": "pressure"})

    new_dispatch = LRPStatus.objects.create(start_time=2.0, state=LRPStatus.State.RUNNING)
    LRPDispatchData.objects.create(status=new_dispatch)

    lrp = FunctionFinderResults()
    lrp.ranking_status_pk = ranking.pk
    lrp.status_row_pk = new_dispatch.pk

    result = lrp.LoadItemFromSessionStore("data", "IndependentDataName1")
    assert result == "pressure", (
        "FunctionFinderResults.LoadItemFromSessionStore must read 'data' keys "
        "from ranking_status_pk. Got: %r" % result
    )
