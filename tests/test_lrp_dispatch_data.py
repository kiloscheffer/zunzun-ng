"""Tests for the LRPDispatchData per-dispatch data row and LRPStatus ownership columns."""

import numpy
import pytest
from django.db import IntegrityError, connection

from zunzun.dispatch_data import load_item, save_items
from zunzun.models import LRPDispatchData, LRPStatus


@pytest.mark.django_db
def test_dispatch_data_cascade_deletes_with_status():
    status = LRPStatus.objects.create(start_time=1.0)
    LRPDispatchData.objects.create(status=status, data={"x": 1}, functionfinder={})
    assert LRPDispatchData.objects.count() == 1
    status.delete()
    assert LRPDispatchData.objects.count() == 0  # cascade


@pytest.mark.django_db
def test_status_ownership_columns_default_empty():
    status = LRPStatus.objects.create(start_time=1.0)
    assert status.owner_session_key == ""
    assert status.owner_ip == ""


@pytest.mark.django_db(transaction=True)
def test_result_token_is_unique_and_columns_present():
    LRPStatus.objects.create(start_time=1.0, result_token="tok-uniq-1")
    with pytest.raises(IntegrityError):  # duplicate token
        LRPStatus.objects.create(start_time=1.0, result_token="tok-uniq-1")
    with connection.cursor() as cursor:
        cols = {
            c.name
            for c in connection.introspection.get_table_description(cursor, "zunzun_lrpstatus")
        }
    assert {"owner_session_key", "owner_ip", "result_token"} <= cols


@pytest.mark.django_db
def test_save_and_load_items_roundtrip_with_numpy():
    status = LRPStatus.objects.create(start_time=1.0)
    save_items(status.pk, "data", {"coef": numpy.array([1.0, 2.0]), "n": numpy.int64(3)})
    assert load_item(status.pk, "data", "coef") == [1.0, 2.0]  # ndarray -> list
    assert load_item(status.pk, "data", "n") == 3  # int64 -> int
    assert load_item(status.pk, "data", "missing", default="x") == "x"


@pytest.mark.django_db
def test_save_items_creates_row_if_absent():
    status = LRPStatus.objects.create(start_time=1.0)
    save_items(status.pk, "functionfinder", {"k": 1})
    assert load_item(status.pk, "functionfinder", "k") == 1
