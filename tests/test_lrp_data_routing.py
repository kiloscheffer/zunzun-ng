"""The LRP base class reads/writes data via the per-dispatch LRPDispatchData
row (zunzun.dispatch_data), not the old per-session SessionStore."""

import pytest

from zunzun.LongRunningProcess.FittingBaseClass import FittingBaseClass
from zunzun.models import LRPStatus


@pytest.mark.django_db
def test_lrp_save_load_routes_to_dispatch_row():
    status = LRPStatus.objects.create(start_time=1.0)
    lrp = FittingBaseClass()
    lrp.status_row_pk = status.pk
    lrp.SaveDictionaryOfItemsToSessionStore("data", {"dimensionality": 2})
    assert lrp.LoadItemFromSessionStore("data", "dimensionality") == 2


def test_data_read_pk_prefers_data_source_pk_then_falls_back():
    """_data_read_pk() returns data_source_pk when set, else status_row_pk."""
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage,
    )

    lrp = StatusMonitoredLongRunningProcessPage()
    # Fresh instance: data_source_pk defaults to None -> falls back.
    lrp.status_row_pk = 5
    assert lrp.data_source_pk is None
    assert lrp._data_read_pk() == 5

    # When data_source_pk is set, it wins over status_row_pk.
    lrp.data_source_pk = 9
    assert lrp._data_read_pk() == 9

    # data_source_pk explicitly None -> fall back even if status_row_pk is 0.
    lrp.data_source_pk = None
    lrp.status_row_pk = 0
    assert lrp._data_read_pk() == 0
