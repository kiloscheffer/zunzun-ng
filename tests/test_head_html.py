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
from django.core.exceptions import ImproperlyConfigured

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


def test_inject_offrequest_globals_sets_head_html():
    """The child renders result pages with render_to_string, which does NOT run
    context processors — so the base class injects head_html by hand. Static, so
    testable without constructing an LRP. Mirrors the demo_mode counterpart."""
    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage as SM,
    )

    with patch("settings.HEAD_HTML", _SENTINEL, create=True):
        assert SM._inject_offrequest_globals({})["head_html"] == _SENTINEL


def test_offrequest_render_carries_head_html():
    """A page rendered off-request (the child path) through the base template the
    result pages extend carries HEAD_HTML raw — what makes the child-written,
    ResultsView-streamed result HTML show the injected markup without a request /
    context processor."""
    from django.template.loader import render_to_string

    from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
        StatusMonitoredLongRunningProcessPage as SM,
    )

    with patch("settings.HEAD_HTML", _SENTINEL, create=True):
        html = render_to_string(
            "zunzun/generic_page_template.html", SM._inject_offrequest_globals({})
        )
    assert _SENTINEL in html


# --- settings._read_head_html(): the HEAD_HTML_FILE load path. The tests above
# patch settings.HEAD_HTML directly and never exercise the actual file read, so
# these cover it: empty-when-unset, BOM stripping (utf-8-sig), and the two
# fail-loud branches (missing file, non-UTF-8). monkeypatch sets the env var the
# helper reads at call time; tmp_path gives a throwaway file.


def test_read_head_html_empty_when_env_unset(monkeypatch):
    """No HEAD_HTML_FILE → empty string, no error (the shipped default)."""
    import settings

    monkeypatch.delenv("HEAD_HTML_FILE", raising=False)
    assert settings._read_head_html() == ""


def test_read_head_html_reads_file_and_strips_bom(tmp_path, monkeypatch):
    """A UTF-8-with-BOM file (common from Windows editors) is read with the BOM
    stripped, so the U+FEFF never leaks into <head>. Proves encoding=utf-8-sig."""
    import settings

    f = tmp_path / "head.html"
    f.write_bytes(b"\xef\xbb\xbf" + _SENTINEL.encode("utf-8"))  # BOM + sentinel
    monkeypatch.setenv("HEAD_HTML_FILE", str(f))
    assert settings._read_head_html() == _SENTINEL


def test_read_head_html_missing_file_fails_loud(tmp_path, monkeypatch):
    """A set-but-missing path raises ImproperlyConfigured (not a silent '')."""
    import settings

    monkeypatch.setenv("HEAD_HTML_FILE", str(tmp_path / "does_not_exist.html"))
    with pytest.raises(ImproperlyConfigured):
        settings._read_head_html()


def test_read_head_html_non_utf8_fails_loud(tmp_path, monkeypatch):
    """A file that is not valid UTF-8 raises ImproperlyConfigured too — the
    UnicodeDecodeError (a ValueError, NOT an OSError) must be caught, else it
    would escape as a raw, path-less traceback."""
    import settings

    f = tmp_path / "bad.html"
    f.write_bytes(b"\xff\xfe\x00invalid utf-8 bytes")  # 0xFF is never valid UTF-8
    monkeypatch.setenv("HEAD_HTML_FILE", str(f))
    with pytest.raises(ImproperlyConfigured):
        settings._read_head_html()
