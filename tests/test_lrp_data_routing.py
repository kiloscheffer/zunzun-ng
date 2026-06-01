"""The LRP base class reads/writes data via the per-dispatch LRPDispatchData
row (zunzun.dispatch_data), not the old per-session SessionStore."""

import pytest
from zunzun.models import LRPStatus
from zunzun.LongRunningProcess.FittingBaseClass import FittingBaseClass


@pytest.mark.django_db
def test_lrp_save_load_routes_to_dispatch_row():
    status = LRPStatus.objects.create(start_time=1.0)
    lrp = FittingBaseClass()
    lrp.status_row_pk = status.pk
    lrp.SaveDictionaryOfItemsToSessionStore("data", {"dimensionality": 2})
    assert lrp.LoadItemFromSessionStore("data", "dimensionality") == 2
