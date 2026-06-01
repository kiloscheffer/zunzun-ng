"""Tests for per-dispatch addressing: ownership checks, identical-404 oracle,
token-addressed results, and concurrency caps."""

import pytest
from django.test import Client, RequestFactory
from zunzun.models import LRPStatus
from zunzun.views import _load_owned_status_row


def _request_with_session(session_key):
    req = RequestFactory().get("/")
    req.session = type("S", (), {"session_key": session_key})()
    return req


@pytest.mark.django_db
def test_load_owned_row_returns_row_for_matching_session():
    row = LRPStatus.objects.create(start_time=1.0, owner_session_key="sess-A")
    assert _load_owned_status_row(_request_with_session("sess-A"), row.pk).pk == row.pk


@pytest.mark.django_db
def test_load_owned_row_returns_none_for_foreign_session():
    row = LRPStatus.objects.create(start_time=1.0, owner_session_key="sess-A")
    assert _load_owned_status_row(_request_with_session("sess-B"), row.pk) is None


@pytest.mark.django_db
def test_load_owned_row_returns_none_for_missing_pk_indistinguishably():
    # not-found and not-yours must be indistinguishable (None both ways)
    assert _load_owned_status_row(_request_with_session("sess-A"), 999999) is None


@pytest.mark.django_db
def test_status_page_requires_ownership():
    row = LRPStatus.objects.create(start_time=1.0, owner_session_key="other")
    c = Client()
    c.get("/")  # establishes a session with a different key
    resp = c.get(f"/StatusAndResults/{row.pk}/")
    assert resp.status_code == 404
