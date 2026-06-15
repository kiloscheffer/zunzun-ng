"""Tests for operator-injectable <head> HTML.

settings.HEAD_HTML is exposed to every base-template page by
zunzun.context_processors.head_html (request path) and, for the child-rendered
result pages, by StatusMonitoredLongRunningProcessPage._inject_offrequest_globals
(off-request path — render_to_string skips context processors). Both read the
ROOT `settings` module (`import settings`, the no-inner-package layout), so these
tests patch `settings.HEAD_HTML` directly via mock.patch(..., create=True) — NOT
@override_settings, which patches the django.conf wrapper this code never reads.
Mirrors tests/test_demo_mode.py.
"""

import os
from unittest.mock import patch

import pytest

# A raw HTML sentinel: a <meta> tag. If it ever renders HTML-escaped (&lt;meta&gt;)
# the |safe filter / autoescape-off contract is broken.
_SENTINEL = '<meta name="head-html-probe" content="zzz-12345" />'


def test_head_html_setting_exists_and_defaults_empty():
    """HEAD_HTML is a str, empty by default when HEAD_HTML_FILE is unset. The
    default is asserted only when the env var is absent (robust against a dev
    machine that exports it — same hardening as the demo-mode setting test)."""
    import settings

    assert isinstance(settings.HEAD_HTML, str)
    if "HEAD_HTML_FILE" not in os.environ:
        assert settings.HEAD_HTML == ""


def test_head_html_context_processor_reflects_setting():
    """The processor returns {'head_html': settings.HEAD_HTML}, ignoring its
    request arg (pass None). Patching the root settings module drives it."""
    from zunzun.context_processors import head_html

    with patch("settings.HEAD_HTML", _SENTINEL, create=True):
        assert head_html(None) == {"head_html": _SENTINEL}
    with patch("settings.HEAD_HTML", "", create=True):
        assert head_html(None) == {"head_html": ""}


@pytest.mark.django_db
def test_head_html_injected_raw_on_home(client, mocked_process_start):
    """GET / renders HEAD_HTML raw (unescaped) inside <head>, positioned before
    <meta charset>. mocked_process_start no-ops HomePageView's housekeeping child."""
    with patch("settings.HEAD_HTML", _SENTINEL, create=True):
        response = client.get("/")
    body = response.content.decode("utf-8")
    assert _SENTINEL in body  # raw, not escaped into &lt;meta&gt;
    head_open = body.index("<head>")
    charset = body.index('<meta charset="UTF-8"', head_open)
    sentinel = body.index(_SENTINEL, head_open)
    assert head_open < sentinel < charset


@pytest.mark.django_db
def test_head_empty_when_unset_on_home(client, mocked_process_start):
    """With HEAD_HTML empty, GET / injects nothing — no probe marker, and the
    space between <head> and <meta charset> is whitespace only (zero change off)."""
    with patch("settings.HEAD_HTML", "", create=True):
        response = client.get("/")
    body = response.content.decode("utf-8")
    assert "head-html-probe" not in body
    head_open = body.index("<head>")
    between = body[head_open + len("<head>") : body.index('<meta charset="UTF-8"', head_open)]
    assert between.strip() == ""


@pytest.mark.django_db
def test_head_html_injected_on_second_page(client):
    """Proves "every base-template page", not just home: the equation-list page
    (a different view + template that also extends the base) carries it too."""
    with patch("settings.HEAD_HTML", _SENTINEL, create=True):
        response = client.get("/AllEquations/2/All/")
    assert _SENTINEL in response.content.decode("utf-8")
