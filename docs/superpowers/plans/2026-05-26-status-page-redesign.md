# Status Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `StatusView`'s hand-rolled HTML string with a Django template that matches the rest of the site, and add a JSON polling endpoint so the progress page updates in place without full-page meta-refresh reloads.

**Architecture:** `/StatusAndResults/` keeps its completion branch (file body or 302 redirect) unchanged, but its in-progress branch now renders `templates/zunzun/status.html` (extending `generic_page_template.html`). A new `/StatusUpdate/` endpoint returns `JsonResponse` for client-side polling; included `StatusPoll.js` polls every 2 seconds and updates the DOM in place. On completion the JSON returns `{"completed": true}` and JS navigates to `/StatusAndResults/`, which re-enters the existing completion branch.

**Tech Stack:** Django 6.0, pytest + pytest-django, simple.css, vanilla ES2015 JS (no framework).

**Reference spec:** `docs/superpowers/specs/2026-05-26-status-page-redesign-design.md`.

---

## File Map

Create:
- `templates/zunzun/status.html` — extends `generic_page_template.html`; in-progress UI with element IDs the JS targets
- `templates/zunzun/javascript/StatusPoll.js` — `setInterval` poll + DOM update
- `tests/test_status_view.py` — view tests for both `StatusView` and `StatusUpdateView`

Modify:
- `zunzun/views.py` — replace inline-HTML in-progress branch of `StatusView` with `render(...)`; add `StatusUpdateView`; **remove** the `time_of_last_status_check` write from `StatusView` (moves to `StatusUpdateView`)
- `urls.py` — add `re_path(r"^StatusUpdate/", zunzun.views.StatusUpdateView)`
- `static/custom.css` — append `.status-dot`, `.status-card`, and `@keyframes status-pulse` (~25 lines)
- `tests/test_urls.py` — add `/StatusUpdate/` resolution case

---

## Task 1: Pin existing StatusView completion behavior with tests

Adds defensive tests that lock in today's `StatusView` behavior so subsequent refactors can't regress it silently. Tests should PASS against current code before any production change.

**Files:**
- Create: `tests/test_status_view.py`

- [ ] **Step 1: Create the test file with three tests pinning current completion behavior**

Write `tests/test_status_view.py`:

```python
"""StatusView and StatusUpdateView tests.

Pins existing completion-branch behavior (file body serve, URL redirect,
key clearing) and exercises the new JSON polling endpoint.
"""
import os
import time

import pytest
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore


def _make_status_session(**kwargs):
    """Create a fresh status SessionStore with provided keys set, save, and
    return it. Caller wires its session_key into request.session.
    """
    s = SessionStore()
    s.create()
    for k, v in kwargs.items():
        s[k] = v
    s.save()
    return s


def _wire_status_session(client, status_session):
    """Set session_key_status on the client's request session so the view
    can find the status SessionStore.
    """
    session = client.session
    session["session_key_status"] = status_session.session_key
    session.save()


@pytest.mark.django_db
def test_status_view_serves_file_body_on_completion(client, tmp_path, monkeypatch):
    """When redirectToResultsFileOrURL is a path inside TEMP_FILES_DIR,
    StatusView reads the file and returns its contents as the response body.
    """
    monkeypatch.setattr(settings, "TEMP_FILES_DIR", str(tmp_path))
    result_file = tmp_path / "result.html"
    result_file.write_text("<html><body>FAKE RESULT</body></html>")

    status_session = _make_status_session(
        redirectToResultsFileOrURL=str(result_file),
    )
    _wire_status_session(client, status_session)

    response = client.get("/StatusAndResults/")
    assert response.status_code == 200
    assert b"FAKE RESULT" in response.content


@pytest.mark.django_db
def test_status_view_redirects_on_completion_url(client):
    """When redirectToResultsFileOrURL is a site-relative URL (does NOT
    start with TEMP_FILES_DIR), StatusView returns HttpResponseRedirect.
    """
    status_session = _make_status_session(
        redirectToResultsFileOrURL="/FunctionFinderResults/2/?RANK=1&unused=1",
    )
    _wire_status_session(client, status_session)

    response = client.get("/StatusAndResults/")
    assert response.status_code == 302
    assert response.url == "/FunctionFinderResults/2/?RANK=1&unused=1"


@pytest.mark.django_db
def test_status_view_clears_redirect_key_after_consuming(client):
    """StatusView must clear redirectToResultsFileOrURL after using it,
    so a subsequent GET to /StatusAndResults/ does not re-fire the redirect.
    """
    status_session = _make_status_session(
        redirectToResultsFileOrURL="/FunctionFinderResults/2/?RANK=1&unused=1",
    )
    _wire_status_session(client, status_session)

    client.get("/StatusAndResults/")

    # Reload the status session from the DB to see the cleared state.
    reloaded = SessionStore(status_session.session_key)
    assert reloaded["redirectToResultsFileOrURL"] == ""
```

- [ ] **Step 2: Run the tests and verify they pass against current code**

Run: `uv run pytest tests/test_status_view.py -v`

Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_status_view.py
git commit -m "test: pin StatusView completion-branch behavior

Three tests covering file-body serve, URL redirect, and key clearing.
Lock-in tests; these pass against current StatusView and prevent
regressions during the upcoming refactor to template-based rendering."
```

---

## Task 2: Add StatusUpdateView endpoint and URL route (TDD)

Adds the new JSON polling endpoint. Writes tests first, watches them fail with 404, then adds the view and the URL.

**Files:**
- Modify: `tests/test_status_view.py`
- Modify: `tests/test_urls.py`
- Modify: `zunzun/views.py` (add `StatusUpdateView` function)
- Modify: `urls.py` (add route)

- [ ] **Step 1: Add the URL resolution test case**

Edit `tests/test_urls.py`, add this row to the `parametrize` list (after `/StatusAndResults/`):

```python
    ("/StatusUpdate/", zunzun.views.StatusUpdateView),
```

- [ ] **Step 2: Append five StatusUpdateView tests to `tests/test_status_view.py`**

```python
@pytest.mark.django_db
def test_status_update_returns_in_progress_json(client):
    status_session = _make_status_session(
        currentStatus="Calculating Error Statistics",
        start_time=time.time() - 84.0,
        timestamp=time.time() - 2.0,
    )
    _wire_status_session(client, status_session)

    response = client.get("/StatusUpdate/")
    assert response.status_code == 200
    data = response.json()
    assert data["completed"] is False
    assert data["currentStatus"] == "Calculating Error Statistics"
    assert data["elapsed"] == "00:01:24"
    assert "serverTime" in data
    assert "lastUpdate" in data
    assert isinstance(data["loadavg"], list)
    assert len(data["loadavg"]) == 3


@pytest.mark.django_db
def test_status_update_returns_completed_when_redirect_set(client):
    """When redirectToResultsFileOrURL is set, the poll endpoint reports
    completion and does NOT clear the key — clearing is owned by StatusView.
    """
    status_session = _make_status_session(
        currentStatus="done",
        start_time=time.time(),
        timestamp=time.time(),
        redirectToResultsFileOrURL="/FunctionFinderResults/2/?RANK=1&unused=1",
    )
    _wire_status_session(client, status_session)

    response = client.get("/StatusUpdate/")
    assert response.status_code == 200
    assert response.json() == {"completed": True}

    # Key must NOT be cleared by the polling endpoint.
    reloaded = SessionStore(status_session.session_key)
    assert reloaded["redirectToResultsFileOrURL"] == "/FunctionFinderResults/2/?RANK=1&unused=1"


@pytest.mark.django_db
def test_status_update_updates_heartbeat(client):
    status_session = _make_status_session(
        currentStatus="working",
        start_time=time.time() - 10.0,
        timestamp=time.time() - 1.0,
    )
    _wire_status_session(client, status_session)

    before = time.time()
    client.get("/StatusUpdate/")
    after = time.time()

    reloaded = SessionStore(status_session.session_key)
    assert before <= reloaded["time_of_last_status_check"] <= after


@pytest.mark.django_db
def test_status_update_400_when_session_missing(client):
    """No session_key_status on the request session -> 400 with no_session."""
    response = client.get("/StatusUpdate/")
    assert response.status_code == 400
    assert response.json() == {"error": "no_session"}


@pytest.mark.django_db
def test_status_update_400_when_required_keys_missing(client):
    """session_key_status present but the status session has no
    currentStatus/start_time/timestamp -> stale_session 400.
    """
    status_session = _make_status_session()  # empty
    _wire_status_session(client, status_session)

    response = client.get("/StatusUpdate/")
    assert response.status_code == 400
    assert response.json() == {"error": "stale_session"}
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_status_view.py -v -k status_update`

Expected: 5 failed (404 status code; URL not registered yet). Also `tests/test_urls.py::test_url_resolves_to_view[/StatusUpdate/-StatusUpdateView]` fails with AttributeError.

- [ ] **Step 4: Add `StatusUpdateView` to `zunzun/views.py`**

Insert after `StatusView` (after the closing `return HttpResponse(s)` on the line currently around 357):

```python
@cache_control(no_cache=True)
def StatusUpdateView(request):
    """JSON polling endpoint for the status page.

    Returns the live status fields (currentStatus, elapsed/serverTime/
    lastUpdate, loadavg) as JSON. On completion, returns {"completed": True}
    and intentionally does NOT clear redirectToResultsFileOrURL — that's
    StatusView's job when the browser follows up.
    """
    from django.http import JsonResponse

    try:
        session_status = SessionStore(request.session["session_key_status"])
    except KeyError:
        return JsonResponse({"error": "no_session"}, status=400)

    # Completion: report and return immediately. Do NOT clear the key.
    if session_status.get("redirectToResultsFileOrURL", ""):
        return JsonResponse({"completed": True})

    try:
        currentStatus = session_status["currentStatus"]
        startTime = session_status["start_time"]
        timeStamp = session_status["timestamp"]
    except KeyError:
        return JsonResponse({"error": "stale_session"}, status=400)

    session_status["time_of_last_status_check"] = time.time()

    save_complete = False
    saveRetries = 0
    while not save_complete:
        try:
            session_status.save()
            save_complete = True
        except Exception as e:
            time.sleep(0.1)
            saveRetries += 1
            if saveRetries > 100:
                raise e

    db.connections.close_all()
    close_old_connections()

    loadavg = platform_compat.get_loadavg()
    now = time.time()
    return JsonResponse({
        "completed": False,
        "currentStatus": currentStatus,
        "elapsed": ConvertSecondsToHMS(now - startTime),
        "serverTime": time.asctime(time.localtime(now))[:-5],
        "lastUpdate": time.asctime(time.localtime(timeStamp))[:-5],
        "loadavg": list(loadavg),
    })
```

- [ ] **Step 5: Add the URL route to `urls.py`**

Insert one line right after the `StatusAndResults/` line:

```python
    re_path(r"^StatusUpdate/", zunzun.views.StatusUpdateView),
```

- [ ] **Step 6: Run all relevant tests to verify they pass**

Run: `uv run pytest tests/test_status_view.py tests/test_urls.py -v`

Expected: All tests pass (3 existing pin tests + 5 new StatusUpdate tests + all URL resolution tests).

- [ ] **Step 7: Commit**

```bash
git add zunzun/views.py urls.py tests/test_status_view.py tests/test_urls.py
git commit -m "feat: add StatusUpdate JSON polling endpoint

New /StatusUpdate/ endpoint returns live status fields as JSON for the
forthcoming client-side polling on the status page. On completion it
reports {completed: true} but does NOT clear redirectToResultsFileOrURL
— that responsibility stays with StatusView when the browser follows up.

Same SQLite-lock retry pattern as StatusView for the heartbeat write."
```

---

## Task 3: Add status-page CSS

Pure additive CSS — no behavior change, no tests required, manual visual check happens in Task 6.

**Files:**
- Modify: `static/custom.css` (append at end)

- [ ] **Step 1: Append the new CSS block to `static/custom.css`**

Add at the end of the file:

```css
/* ------------------------------------------------------------------------ */
/*   STATUS PAGE                                                            */
/*   Pulsing dot affordance next to the heading while a fit is in progress; */
/*   status card highlights the live currentStatus message.                 */
/* ------------------------------------------------------------------------ */

.status-dot {
  display: inline-block;
  width: 0.6em;
  height: 0.6em;
  margin-left: 0.4em;
  border-radius: 50%;
  background: var(--accent);
  animation: status-pulse 1.4s ease-in-out infinite;
  vertical-align: middle;
}

@keyframes status-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.3; }
}

.status-card {
  background: var(--accent-bg);
  border-radius: var(--standard-border-radius);
  padding: 1rem 1.25rem;
  margin: 1rem 0;
}
```

- [ ] **Step 2: Commit**

```bash
git add static/custom.css
git commit -m "style: add status-dot pulse + status-card for status page"
```

---

## Task 4: Add StatusPoll.js

Vanilla JS, no tests (browser-only). Manual verification in Task 6.

**Files:**
- Create: `templates/zunzun/javascript/StatusPoll.js`

- [ ] **Step 1: Create the JS file**

Write `templates/zunzun/javascript/StatusPoll.js`:

```javascript
/* StatusPoll.js — polls /StatusUpdate/ every 2 seconds and updates the
 * status page DOM in place. On completion, navigates to /StatusAndResults/
 * which re-enters StatusView's completion branch (file body or redirect).
 *
 * Failure tolerance: any fetch/parse exception is swallowed; the next
 * 2-second tick retries. At 2s intervals a missed poll is invisible.
 */
(function () {
  var POLL_INTERVAL_MS = 2000;

  function applyUpdate(data) {
    if (data.completed === true) {
      window.location.assign('/StatusAndResults/');
      return;
    }
    /* currentStatus contains <br> tags written by the LRP (server-side),
     * so innerHTML is intentional. */
    var statusEl = document.getElementById('currentStatus');
    if (statusEl) statusEl.innerHTML = data.currentStatus;

    setText('elapsedTime', data.elapsed);
    setText('serverTime', data.serverTime);
    setText('lastUpdate', data.lastUpdate);

    if (data.loadavg && data.loadavg.length === 3) {
      setText('load1', data.loadavg[0]);
      setText('load5', data.loadavg[1]);
      setText('load15', data.loadavg[2]);
    }
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function poll() {
    fetch('/StatusUpdate/', { credentials: 'same-origin' })
      .then(function (response) {
        if (!response.ok) return;  /* 4xx/5xx: retry next tick */
        return response.json();
      })
      .then(function (data) {
        if (data) applyUpdate(data);
      })
      .catch(function () { /* network blip: swallow, retry next tick */ });
  }

  /* First poll fires immediately to refresh between initial render and JS load. */
  poll();
  setInterval(poll, POLL_INTERVAL_MS);
})();
```

- [ ] **Step 2: Commit**

```bash
git add templates/zunzun/javascript/StatusPoll.js
git commit -m "feat: add StatusPoll.js client-side polling for status page"
```

---

## Task 5: Add status.html template and refactor StatusView to render it (TDD)

The biggest task: writes the template, then refactors `StatusView` to render it. TDD via new tests asserting on DOM markers.

**Files:**
- Create: `templates/zunzun/status.html`
- Modify: `zunzun/views.py` (replace in-progress branch in `StatusView`)
- Modify: `tests/test_status_view.py` (add in-progress-render tests)

- [ ] **Step 1: Add four in-progress render tests to `tests/test_status_view.py`**

Append to the test file:

```python
@pytest.mark.django_db
def test_status_view_renders_template_when_in_progress(client):
    """When no redirect is set, StatusView renders the status.html template
    with the expected DOM markers the JS will target.
    """
    status_session = _make_status_session(
        currentStatus="Calculating Error Statistics",
        start_time=time.time() - 30.0,
        timestamp=time.time() - 1.0,
    )
    _wire_status_session(client, status_session)

    response = client.get("/StatusAndResults/")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")

    body = response.content.decode("utf-8")
    # JS-targeted element IDs must be present.
    assert 'id="currentStatus"' in body
    assert 'id="elapsedTime"' in body
    assert 'id="serverTime"' in body
    assert 'id="lastUpdate"' in body
    assert 'id="load1"' in body
    assert 'id="load5"' in body
    assert 'id="load15"' in body
    # The poll script must be included.
    assert "StatusPoll.js" in body
    # The currentStatus value from the session must be rendered into the initial frame.
    assert "Calculating Error Statistics" in body


@pytest.mark.django_db
def test_status_view_extends_generic_template(client):
    """Initial render should carry the site chrome (header logo, footer, css)."""
    status_session = _make_status_session(
        currentStatus="working",
        start_time=time.time(),
        timestamp=time.time(),
    )
    _wire_status_session(client, status_session)

    body = client.get("/StatusAndResults/").content.decode("utf-8")
    assert "small_logo.png" in body          # header logo from generic template
    assert "custom.css" in body              # site CSS
    assert "FindCurves" in body              # footer link


@pytest.mark.django_db
def test_status_view_does_not_write_heartbeat(client):
    """Heartbeat write moved to StatusUpdateView; StatusView's initial render
    must NOT update time_of_last_status_check.
    """
    status_session = _make_status_session(
        currentStatus="working",
        start_time=time.time(),
        timestamp=time.time(),
        time_of_last_status_check=0.0,  # sentinel
    )
    _wire_status_session(client, status_session)

    client.get("/StatusAndResults/")

    reloaded = SessionStore(status_session.session_key)
    assert reloaded["time_of_last_status_check"] == 0.0


@pytest.mark.django_db
def test_status_view_400_when_required_keys_missing(client):
    """If currentStatus/start_time/timestamp are missing, StatusView returns
    a user-visible 'delete your cookie' message (unchanged behavior).
    """
    status_session = _make_status_session()  # empty
    _wire_status_session(client, status_session)

    response = client.get("/StatusAndResults/")
    # Existing behavior is HttpResponse(str), which is 200 with an error message body.
    assert response.status_code == 200
    assert b"stale browser cookie" in response.content or b"session data" in response.content
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_status_view.py -v -k "renders_template or extends_generic or heartbeat or 400_when_required"`

Expected: `test_status_view_renders_template_when_in_progress` fails (current view emits raw HTML without `id="currentStatus"` markers), `test_status_view_extends_generic_template` fails (no `small_logo.png`), `test_status_view_does_not_write_heartbeat` fails (current StatusView writes the heartbeat). The 400-when-required test should already pass against current code.

- [ ] **Step 3: Create the template `templates/zunzun/status.html`**

```html
{% extends "zunzun/generic_page_template.html" %}

{% block title %}
    ZunZunNG - Working on your fit
{% endblock %}

{% block additional_javascript %}
    {% include "zunzun/javascript/StatusPoll.js" %}
{% endblock %}

{% block body_contents %}
<div>
  <h2>Working on your fit<span class="status-dot" aria-hidden="true"></span></h2>

  <div class="status-card" id="currentStatus">{{ currentStatus }}</div>

  <h3>Timing</h3>
  <dl class="stats-list">
    <dt>Elapsed time</dt>     <dd id="elapsedTime">{{ elapsed }}</dd>
    <dt>Server time</dt>      <dd id="serverTime">{{ serverTime }}</dd>
    <dt>Last update</dt>      <dd id="lastUpdate">{{ lastUpdate }}</dd>
  </dl>

  <h3>Server load</h3>
  <dl class="server-load">
    <dt>1 minute</dt>         <dd id="load1">{{ loadavg.0 }}</dd>
    <dt>5 minutes</dt>        <dd id="load5">{{ loadavg.1 }}</dd>
    <dt>15 minutes</dt>       <dd id="load15">{{ loadavg.2 }}</dd>
  </dl>

  <p><small>
    Load &lt; {{ coreCount }} is light;
    &ge; {{ coreCount }} means cores are saturated.
  </small></p>
</div>
{% endblock %}
```

Note: The `StatusPoll.js` include is via `{% include %}` because the existing pattern in `equation_fit_or_characterizer_results.html` uses `{% include "zunzun/javascript/JavascriptForEvaluateAtAPoint.js" %}` inside `{% block additional_javascript %}` — i.e. JS lives in the templates tree and is inlined into the page rather than served as a static file. Follow the existing pattern.

- [ ] **Step 4: Refactor `StatusView` in `zunzun/views.py`**

Replace the body of `StatusView` (currently lines ~251–357) with this. The completion branch stays byte-for-byte identical; only the in-progress branch and heartbeat removal change:

```python
@cache_control(no_cache=True)
def StatusView(request):
    try:
        session_status = SessionStore(request.session["session_key_status"])
    except:
        return HttpResponse("I could not read your session data, please try again.")

    # Completion handoff: read, clear, serve file body OR HttpResponseRedirect.
    # Behavior unchanged from the original implementation.
    if "redirectToResultsFileOrURL" in session_status:
        if session_status["redirectToResultsFileOrURL"] != "":
            redirect = session_status["redirectToResultsFileOrURL"]
            session_status["redirectToResultsFileOrURL"] = ""

            s = session_status
            save_complete = False
            saveRetries = 0
            while not save_complete:
                try:
                    s.save()
                    save_complete = True
                except Exception as e:
                    time.sleep(0.1)
                    saveRetries += 1
                    if saveRetries > 100:
                        raise e

            db.connections.close_all()
            close_old_connections()

            if redirect.startswith(settings.TEMP_FILES_DIR):
                s = open(redirect, "r").read()
                return HttpResponse(s)
            else:
                return HttpResponseRedirect(redirect)

    # In-progress branch: render the template. Heartbeat write moved to
    # StatusUpdateView so there is a single owner of that side effect.
    try:
        currentStatus = session_status["currentStatus"]
        startTime = session_status["start_time"]
        timeStamp = session_status["timestamp"]
    except:
        return HttpResponse(
            "I could not read your session data, my apologies. This is usually caused by a stale browser cookie. Please delete the ZunZunNG browser cookie and try again."
        )

    now = time.time()
    loadavg = platform_compat.get_loadavg()
    return render(request, "zunzun/status.html", {
        "title_string": "ZunZunNG - Working on your fit",
        "header_text": "ZunZunNG",
        "currentStatus": currentStatus,
        "elapsed": ConvertSecondsToHMS(now - startTime),
        "serverTime": time.asctime(time.localtime(now))[:-5],
        "lastUpdate": time.asctime(time.localtime(timeStamp))[:-5],
        "loadavg": list(loadavg),
        "coreCount": multiprocessing.cpu_count(),
    })
```

Note: `header_text` and `title_string` are required by `generic_page_template.html`. Check one of the existing extending templates (e.g. `generic_error.html`) to confirm — `generic_error.html` only supplies `{% block title %}`, which suggests the header defaults via a context processor or via the home page. Inspect what gets passed today.

If `header_text` ends up undefined at template-time, the page still renders but the header text is empty. If that visual regression appears in Task 6 manual verification, fix it by checking how `HomePageView` builds its context and matching.

- [ ] **Step 5: Run all status-related tests to verify they pass**

Run: `uv run pytest tests/test_status_view.py -v`

Expected: All 12 tests in the file pass (3 pinning + 5 StatusUpdate + 4 in-progress render).

- [ ] **Step 6: Run the full pytest suite to catch unintended regressions**

Run: `uv run pytest tests/ -v`

Expected: All tests pass. If anything fails in `test_views_dispatch.py::test_status_view_renders_without_session_keys`, the broad bare-except in `StatusView` is still in place and that test expected 200/302/400/404 — verify it still passes.

- [ ] **Step 7: Commit**

```bash
git add templates/zunzun/status.html zunzun/views.py tests/test_status_view.py
git commit -m "feat: render status page from template, drop meta-refresh

StatusView's in-progress branch now renders templates/zunzun/status.html
which extends generic_page_template.html and matches the rest of the site
visually. The completion branch (file body or 302 redirect) is unchanged.

The time_of_last_status_check heartbeat write moves from StatusView to
StatusUpdateView so there is a single owner of that side effect; the
initial page render no longer counts as a status check.

Polling is now driven by StatusPoll.js fetching /StatusUpdate/ every 2s
and updating the DOM in place — no more full-page meta-refresh flash."
```

---

## Task 6: Manual browser verification

UI verification: the new page must render correctly, poll without flashing, and complete cleanly. Per CLAUDE.md, UI changes require browser-based testing, not just passing unit tests.

- [ ] **Step 1: Start the dev server**

Run: `uv run python manage.py runserver`

Expected: Server listens on http://127.0.0.1:8000/.

- [ ] **Step 2: Run a 2D polynomial fit and watch the status page**

In a browser, navigate to http://127.0.0.1:8000/, choose a 2D polynomial fit, paste the sample dataset from `scripts/smoke_test.py` (or any small dataset like `1 2\n2 4\n3 6\n4 8\n5 10`), and submit.

Verify on the status page:
- Header has the ZunZunNG logo (matches the rest of the site)
- Footer has the three-column links block
- `Working on your fit` heading has a small pulsing dot next to it
- The currentStatus card updates in place every ~2 seconds with no white-flash
- Elapsed time increments in seconds without page reload
- Server load values refresh
- When the fit completes, the browser navigates smoothly to the results page

- [ ] **Step 3: Run a 3D polynomial fit (longer, more status transitions)**

Repeat with a 3D fit. Per `CLAUDE.md` and the saved 3d-fit-slow-on-windows memory, this takes longer (≥1800s budget on Windows). The point is to watch many `currentStatus` transitions: "Calculating Data Statistics", "Generating List Of Text Reports", "Created N of M Reports and Graphs", etc.

Verify: the currentStatus card shows each transition without disruption; no JS errors in the browser console.

- [ ] **Step 4: Run the smoke test to confirm end-to-end completion still works**

In a separate terminal:

Run: `uv run python scripts/smoke_test.py`

Expected: smoke test passes. The smoke test polls `/StatusAndResults/` and asserts on the completion body — the completion branch was preserved verbatim, so this should pass without modification.

- [ ] **Step 5: If everything verified, no commit needed.**

If Task 6 found a visual regression that required fixing (e.g., missing `header_text` context value, JS console errors), make the fix, run pytest again, and commit the fix.

---

## Self-Review Pass

**Spec coverage:**
- Two-URL architecture (StatusAndResults preserves completion branch + StatusUpdate adds JSON polling) → Task 2 + Task 5
- `templates/zunzun/status.html` extending generic template, reusing `.stats-list` + `.server-load`, with pulsing dot → Task 5 template
- `templates/zunzun/javascript/StatusPoll.js`, ~30 lines, 2s setInterval, completion=window.location.assign → Task 4
- `static/custom.css` ~25 lines (.status-dot, .status-card, @keyframes) → Task 3
- StatusView refactor: keep completion branch verbatim; replace in-progress; remove heartbeat write → Task 5 step 4
- StatusUpdateView: heartbeat owner, JSON in-progress shape, completion = {completed: true} without clearing key, no @ratelimit → Task 2
- Drop 3-line load legend, replace with one-liner using `coreCount` → Task 5 template body
- Remove `<meta http-equiv=REFRESH>` → done implicitly by switching to the new template (the old string-builder is gone)
- Unit tests (in-progress render, file-body serve, URL redirect, key clearing, JSON in-progress shape, JSON completion, heartbeat update, no-session 400, stale-session 400) → Tasks 1, 2, 5
- URL test for `/StatusUpdate/` → Task 2 step 1
- Smoke test no-change → Task 6 step 4
- Manual browser check → Task 6

**Placeholder scan:** Searched for "TBD", "TODO", "implement later", "appropriate error handling", "similar to Task". None found. Step 4 of Task 5 has one note pointing forward ("If `header_text` ends up undefined ... fix it") — this is acceptable as a conditional fixup directive, not a placeholder; the primary instruction (replace the function body with the shown code) is complete.

**Type consistency:** `ConvertSecondsToHMS`, `platform_compat.get_loadavg`, `SessionStore`, `close_old_connections`, `db.connections.close_all` — all used identically to the existing `StatusView`. Element IDs `currentStatus`/`elapsedTime`/`serverTime`/`lastUpdate`/`load1`/`load5`/`load15` are consistent across the template, the JS, and the tests. JSON keys `completed`/`currentStatus`/`elapsed`/`serverTime`/`lastUpdate`/`loadavg` are consistent between the view and the JS consumer.
