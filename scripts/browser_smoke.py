"""Browser-level smoke test for the client-side status poll.

Drives the ONE page flow no other layer covers: StatusPoll.js executing in
a real browser. pytest covers the server views; scripts/smoke_test.py polls
/StatusAndResults/ server-side with requests, bypassing the page JS
entirely. A defect that breaks only the client-side poll (e.g. the
2026-06-02 head-timing regression: bootstrap ran at <head>-parse time,
data-status-pk didn't exist yet, the poll loop never started) passes every
other gate green. This script closes that gap. Spec:
docs/superpowers/specs/2026-06-10-browser-status-poll-smoke-design.md

Scenario: browser_status_poll_2D
  1. Dispatch a 2D polynomial-quadratic fit with requests (byte-identical
     to smoke's polynomial_quadratic_2D dispatch), capture the status pk.
  2. Transplant the requests-session cookies into a headless-Chromium
     context (/StatusAndResults/<pk>/ and /StatusUpdate/<pk>/ are gated on
     owner_session_key; a cookie-less browser 404s).
  3. Open /StatusAndResults/<pk>/ and assert, event-based with generous
     ceilings (never on the 2 s poll cadence or intermediate DOM states):
       a. at least one GET /StatusUpdate/<pk>/ fires (the poll started);
       b. the page navigates to /Results/<token>/ (StatusPoll.js saw
          {"completed": true}; StatusView 302s terminal rows there);
       c. the final page carries a results marker (not an error shell).

Prerequisites (mirrors smoke_test.py: real session_db, migrate first):
  uv sync --group browser
  uv run playwright install chromium
  uv run python manage.py migrate

Usage:
  uv run python scripts/browser_smoke.py
"""

import os
import subprocess
import sys

import requests

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
except ImportError:
    print(
        "playwright is not installed. Set up the browser group first:\n"
        "  uv sync --group browser\n"
        "  uv run playwright install chromium",
        file=sys.stderr,
    )
    sys.exit(2)

from smoke_test import (
    _POLY_QUAD_FIELDS,
    _extract_pk_from_redirect,
    _find_free_port,
    _wait_for_port,
)

# Absolute path to the project root (manage.py lives here). Derived from
# __file__ so the script works regardless of the process cwd.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# First marker from smoke's _POLY_EXPECTED_MARKERS: present on every
# successful polynomial result page, absent from error shells.
_RESULTS_MARKER = "Coefficient and Fit Statistics"

_POLL_FIRES_TIMEOUT_MS = 30_000  # first poll fires immediately on start()
_COMPLETION_TIMEOUT_MS = 300_000  # 2D quadratic fit budget (<60 s typical)


def _run_browser_status_poll_2d(session: requests.Session, base: str) -> str | None:
    """Returns None on success, an error string on failure (smoke convention)."""
    name = "browser_status_poll_2D"

    # Cookie warmup — the fit dispatch requires session["cookie_test"], and
    # the fit-interface GET is @cache_control(no_cache=True) so it always
    # sets it (GET / is @cache_page-cached and cannot be relied on; see the
    # warmup comment in smoke_test._run_concurrent_2D_scenario).
    interface_url = base + "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/"
    session.get(interface_url)

    # Dispatch server-side; the browser's job is the poll, not the form UI.
    resp = session.post(interface_url, data=_POLY_QUAD_FIELDS, allow_redirects=True)
    pk = _extract_pk_from_redirect(resp, base)
    if pk is None:
        return f"[{name}] could not extract dispatch pk from POST redirect"

    console_lines: list[str] = []
    page_errors: list[str] = []
    poll_requests: list[str] = []

    def _is_poll(req) -> bool:
        return f"/StatusUpdate/{pk}/" in req.url

    def _track_poll(req) -> None:
        if _is_poll(req):
            poll_requests.append(req.url)

    def _diagnostics() -> str:
        return (
            f"  observed /StatusUpdate/ requests: {len(poll_requests)} "
            f"(last 3: {poll_requests[-3:]!r})\n"
            f"  console: {console_lines!r}\n"
            f"  pageerrors: {page_errors!r}"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context()
            context.add_cookies(
                [{"name": c.name, "value": c.value, "url": base} for c in session.cookies]
            )
            page = context.new_page()
            page.on("console", lambda msg: console_lines.append(f"[{msg.type}] {msg.text}"))
            page.on("pageerror", lambda exc: page_errors.append(repr(exc)))
            page.on("request", _track_poll)

            # Assertion (a): the poll starts. This alone catches the
            # head-timing regression class (symptom: zero poll requests).
            try:
                with page.expect_request(_is_poll, timeout=_POLL_FIRES_TIMEOUT_MS):
                    page.goto(f"{base}/StatusAndResults/{pk}/")
            except PlaywrightTimeout:
                return (
                    f"[{name}] no /StatusUpdate/{pk}/ request observed within "
                    f"{_POLL_FIRES_TIMEOUT_MS // 1000}s — the client-side poll "
                    f"never started (page url: {page.url})\n" + _diagnostics()
                )

            # Assertion (b): completion navigation to /Results/<token>/.
            try:
                page.wait_for_url("**/Results/**", timeout=_COMPLETION_TIMEOUT_MS)
            except PlaywrightTimeout:
                return (
                    f"[{name}] page never reached /Results/ within "
                    f"{_COMPLETION_TIMEOUT_MS // 1000}s (page url: {page.url})\n" + _diagnostics()
                )

            # Assertion (c): the results actually rendered.
            if _RESULTS_MARKER not in page.content():
                return (
                    f"[{name}] final page lacks results marker "
                    f"{_RESULTS_MARKER!r} (page url: {page.url})\n" + _diagnostics()
                )
        finally:
            browser.close()

    print(f"[{name}] OK — polls observed: {len(poll_requests)}, landed on /Results/")
    return None


def run_browser_smoke() -> int:
    port = _find_free_port()
    base = f"http://127.0.0.1:{port}"
    # Use manage.py runserver (not waitress-serve) so that 'runserver' appears
    # in sys.argv inside the server process, which flips settings.DEBUG=True
    # and enables django.contrib.staticfiles to serve /static/.  Without this
    # jQuery 404s and the template's own $(document).ready(...) raises
    # "$ is not defined" — generic_page_template.html splices StatusPoll.js
    # into the SAME <head> <script> element after that call, so the
    # ReferenceError aborts the block before StatusPoll's IIFE ever runs and
    # the poll never starts (StatusPoll.js itself is jQuery-free).
    # --noreload suppresses the file-watcher child process, keeping
    # subprocess management simple and proc.terminate() reliable.
    proc = subprocess.Popen(
        [sys.executable, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
        cwd=_PROJECT_ROOT,
    )
    try:
        if not _wait_for_port(port):
            print("ERROR: server never became ready", file=sys.stderr)
            return 1
        session = requests.Session()
        err = _run_browser_status_poll_2d(session, base)
        if err:
            print("BROWSER SMOKE FAILED:", file=sys.stderr)
            print(f"  {err}", file=sys.stderr)
            return 1
        print("BROWSER SMOKE OK")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(run_browser_smoke())
