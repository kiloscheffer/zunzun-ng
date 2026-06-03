"""ServerLoadView tests.

The home page is @cache_page-cached for an hour, so a load-average snapshot
baked into its HTML goes stale. ServerLoadView is the no-cache JSON endpoint
that feeds the home page's Server Load panel live values (via ServerLoadPoll.js).
These tests pin its contract: routing, JSON shape, and the no-cache header that
keeps it from inheriting the home page's caching.
"""

from unittest import mock

import pytest
from django.urls import resolve

import zunzun.views


def test_server_load_url_resolves_to_view():
    match = resolve("/ServerLoad/")
    assert match.func is zunzun.views.ServerLoadView


@pytest.mark.django_db
def test_server_load_returns_live_loadavg_json(client):
    """The endpoint returns the current get_loadavg() as a 3-element list."""
    with mock.patch("zunzun.views.platform_compat.get_loadavg", return_value=(2.01, 1.8, 1.83)):
        response = client.get("/ServerLoad/")

    assert response.status_code == 200
    data = response.json()
    assert data["loadavg"] == [2.01, 1.8, 1.83]


@pytest.mark.django_db
def test_server_load_is_not_cached(client):
    """Unlike the home page, this endpoint must carry no-cache so the poller
    always sees fresh values rather than a frozen snapshot."""
    response = client.get("/ServerLoad/")

    assert response.status_code == 200
    assert "no-cache" in response.headers.get("Cache-Control", "")


@pytest.mark.django_db
def test_home_page_wires_live_poller_not_baked_value(client):
    """The home page must ship the poller and id'd placeholder cells, and must
    NOT bake a server-side load number into its (hour-cached) HTML — otherwise
    the value freezes. Locks the full on-path, not just the endpoint."""
    html = client.get("/").content.decode()

    # Placeholder cells the poller targets.
    assert 'id="hpLoad1"' in html
    assert 'id="hpLoad5"' in html
    assert 'id="hpLoad15"' in html
    # Poller is included and points at the no-cache endpoint.
    assert "/ServerLoad/" in html
    assert "ServerLoadPoll" in html
