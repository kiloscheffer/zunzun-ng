import pytest
from zunzun.models import LRPStatus, LRPDispatchData


@pytest.mark.django_db
def test_dispatch_data_cascade_deletes_with_status():
    status = LRPStatus.objects.create(start_time=1.0, result_token="tok-a")
    LRPDispatchData.objects.create(status=status, data={"x": 1}, functionfinder={})
    assert LRPDispatchData.objects.count() == 1
    status.delete()
    assert LRPDispatchData.objects.count() == 0  # cascade


@pytest.mark.django_db
def test_status_ownership_columns_default_empty():
    status = LRPStatus.objects.create(start_time=1.0, result_token="tok-b")
    assert status.owner_session_key == ""
    assert status.owner_ip == ""
