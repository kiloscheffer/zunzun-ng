# Status page redesign: live polling, site-aligned styling

**Date:** 2026-05-26
**Status:** Approved (design); pending implementation plan
**Touches:** `zunzun/views.py`, `urls.py`, `templates/zunzun/status.html` (new), `templates/zunzun/javascript/StatusPoll.js` (new), `static/custom.css`, `tests/test_status_view.py` (new), `tests/test_urls.py`

## Problem

`StatusView` in `zunzun/views.py` (lines 250–357) is the only page on the site that hand-builds raw HTML strings instead of rendering a Django template. It does not load the site's CSS (`modern-normalize`, `simple.css`, `custom.css`), has no header logo, no footer, no shared font, and uses `<pre>` and `<TABLE>` carried forward from the 2016 codebase. Every other page extends `templates/zunzun/generic_page_template.html`.

The page also reloads every 3 seconds via `<meta http-equiv=REFRESH>`, which causes a visible white flash on each refresh and discards browser state (scroll position, selection).

Goal: bring the status page in line with the rest of the site visually, and replace the meta-refresh full-page reload with in-place JSON polling.

## Scope and non-goals

In scope:
- Render the in-progress status page through `generic_page_template.html` like every other page.
- Add a JSON polling endpoint and client-side JS that updates the DOM in place.
- Preserve the existing completion handoff (`StatusView`'s redirect/file-serving branch) byte-for-byte.

Out of scope:
- Changing what `currentStatus` strings look like, or where they are written from the `LongRunningProcess/` classes.
- Adding a real progress percentage (the LRPs don't expose one).
- Replacing the SQLite session store, or revisiting the three-store architecture.
- Touching the rate-limiting middleware or `CommonToAllViews`'s 5-second penalty.

## Architecture

The status flow becomes two URLs:

| URL | Role |
|---|---|
| `GET /StatusAndResults/` | Initial render of the in-progress page. Also the completion handler — when `redirectToResultsFileOrURL` is set in the status session, serves the generated file or returns `HttpResponseRedirect`. **Completion-branch behavior is unchanged** from the current implementation. |
| `GET /StatusUpdate/` (new) | Returns a `JsonResponse` with the live status fields. Updates `time_of_last_status_check` in the status session using the same SQLite-lock retry pattern as the rest of the codebase. |

The status page includes a small JS file that polls `/StatusUpdate/` every 2 seconds and updates the DOM in place. When the JSON response indicates completion, JS navigates the browser to `/StatusAndResults/`, which re-enters the existing completion branch of `StatusView` and serves the file/redirect exactly as today.

**Rationale for keeping the completion branch in `StatusView`.** The completion branch is the load-bearing, regression-sensitive piece — it handles both filesystem-path completions (file body served in-place) and site-relative-URL completions (302 redirect), written from seven different sites under `zunzun/LongRunningProcess/`. Leaving it untouched and only swapping the "still working" branch makes the new feature additive: polling layers on top of behavior already covered by the smoke test.

## Components

### `templates/zunzun/status.html` (new)

Extends `generic_page_template.html`. Layout in the `body_contents` block:

```
┌─────────────────────────────────────────┐
│  Working on your fit  ● (pulsing dot)   │
│                                         │
│  ┌─ status card ──────────────────────┐ │
│  │  {currentStatus innerHTML}         │ │
│  └─────────────────────────────────────┘ │
│                                         │
│  Elapsed time     00:01:24              │
│  Server time      14:32:08              │
│  Last update      14:32:06              │
│                                         │
│  Server load                            │
│    1 minute       0.42                  │
│    5 minutes      0.51                  │
│   15 minutes      0.45                  │
│                                         │
│  Load < {cpu_count} is light; ≥        │
│  {cpu_count} means cores are saturated. │
└─────────────────────────────────────────┘
```

Key choices:
- Reuses existing CSS classes — no new layout patterns invented. `.stats-list` (already in `custom.css`) styles the elapsed/server/last-update dl. `.server-load` (already in `custom.css`, partial at `templates/zunzun/divs/server_load.html`) styles the load-average dl. The status card uses simple.css's `--accent-bg` panel styling already used for code blocks.
- The pulsing dot is a small `<span class="status-dot">` next to the page heading. ~10 lines of CSS added to `custom.css`: `@keyframes pulse` toggling opacity 1 → 0.3 → 1 over 1.4s, applied to a 0.6rem-diameter circle styled with `var(--accent)`. No image asset, no spinner library.
- Drops the verbose 3-line `<TABLE>` legend (currently: "Load < N means cores light", "Load = N means each averages 100% with one user", "Load > N means each averages 100% with multiple users") in favor of one compact sentence underneath the load values, parameterized on `cpu_count`. The signal "I'm running over my budget" is one bit, not three.
- The `<meta http-equiv=REFRESH>` tag is **removed**. The page is intended to be polled by JS, not reloaded by the browser.

Element IDs the JS targets:
- `#currentStatus` — the status card's inner element (innerHTML)
- `#elapsedTime`, `#serverTime`, `#lastUpdate` — `<dd>` cells in the stats list
- `#load1`, `#load5`, `#load15` — `<dd>` cells in the load list

### `templates/zunzun/javascript/StatusPoll.js` (new)

Included via the existing `{% block additional_javascript %}` slot in `generic_page_template.html`, same pattern as `JavascriptForEvaluateAtAPoint.js`. About 30 lines:

- `setInterval(poll, 2000)` calling `fetch('/StatusUpdate/', {credentials: 'same-origin'})`
- On response, parse JSON and update the six target elements. `currentStatus` is set via `innerHTML` (the LRPs write strings containing `<br>` tags); the other fields are plain strings set via `textContent`.
- On `data.completed === true`: `window.location.assign('/StatusAndResults/')`. This re-enters `StatusView`'s completion branch.
- On fetch failure (network blip, server hiccup): swallow the exception silently and let the next interval try again. No backoff, no toast, no retry counter — at 2s intervals a missed poll is invisible to the user.
- No first-time delay; first poll runs immediately on page load to refresh state that may have advanced between the initial render and JS execution.

Why `innerHTML` for `currentStatus` is safe: the LRPs write the string into the session from server-side Python (see grep of `currentStatus` writes in `StatusMonitoredLongRunningProcessPage.py`). No path injects user-supplied content into `currentStatus`. The HTML in those strings is intentional (`<br>` tags for line breaks, parallel-process count). Treating it as text would render the tags literally.

### `zunzun/views.py`

**`StatusView`** — minimal change:
- The completion branch (reads `redirectToResultsFileOrURL`, clears it, serves file body or returns `HttpResponseRedirect`) is preserved verbatim.
- The "still working" branch that currently builds the raw HTML string (lines 309–357) is replaced with `render(request, "zunzun/status.html", context)`. The context contains `currentStatus`, `elapsed` (preformatted HH:MM:SS), `serverTime`, `lastUpdate` (both as `time.asctime`-formatted strings, same trim as today), and `loadavg` (3-tuple) plus `coreCount`. These are used to render the *first* frame of the page; thereafter JS owns the DOM.
- The `time_of_last_status_check` write that currently happens on every `StatusView` call is **removed** from `StatusView` (moved to `StatusUpdateView`). The initial render no longer counts as a status check; the first JS poll a few hundred ms later is what bumps the heartbeat. This is a deliberate change: keeps a single owner of the heartbeat and avoids two redundant SQLite writes back-to-back when the user first lands on the page.

**`StatusUpdateView`** (new):
- Reads `session_key_status` from the request session; on miss, `JsonResponse({"error": "no_session"}, status=400)`.
- If `redirectToResultsFileOrURL` is set and non-empty, returns `JsonResponse({"completed": True})` and **does not clear the key**. Clearing is the responsibility of `StatusView` when the browser follows up. This keeps one owner of the clear-and-serve transition.
- Otherwise reads `currentStatus`, `start_time`, `timestamp`; computes `elapsed` via `ConvertSecondsToHMS`; formats `serverTime` and `lastUpdate` the same way as the current code (`time.asctime(time.localtime(...))[:-5]` — trims the year off, matching today's display); reads `loadavg` via `platform_compat.get_loadavg()`; returns `JsonResponse({...})`.
- Writes `time_of_last_status_check = time.time()` and saves with the same 100×@10Hz SQLite-lock retry loop used elsewhere in this view module.
- Decorated with `@cache_control(no_cache=True)`, same as `StatusView`.
- **Not** decorated with `@ratelimit`. `StatusView` is also not rate-limited today; the heartbeat IS the throttle; rate-limiting your own progress page is hostile. (`CommonToAllViews`'s 5-sec penalty on `request.limited` would specifically break polling.)

### `urls.py`

One new line: `re_path(r"^StatusUpdate/", zunzun.views.StatusUpdateView)`. Placed adjacent to the existing `StatusAndResults/` entry.

### `static/custom.css`

Add ~25 lines:

```css
/* Status page: pulsing-dot affordance next to the heading while polling. */
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

/* Status card: highlights the live currentStatus message. */
.status-card {
  background: var(--accent-bg);
  border-radius: var(--standard-border-radius);
  padding: 1rem 1.25rem;
  margin: 1rem 0;
}
```

`@media (prefers-reduced-motion: reduce)` is honored implicitly via `simple.css`'s global `transition: none` override for that media query; the pulse is short and low-amplitude enough that this is acceptable. (If a reviewer prefers an explicit reduced-motion stop, that's a 4-line addition to the same block.)

## Data flow

```
Browser                          Server                       Child process
   │                                 │                              │
   │ GET /StatusAndResults/          │                              │
   ├────────────────────────────────>│                              │
   │                                 │ session_status read          │
   │                                 │ redirectToResultsFileOrURL? ─┤(no)
   │                                 │ render status.html           │
   │<────────────────────────────────┤                              │
   │ (page + StatusPoll.js)          │                              │
   │                                 │                              │
   │ every 2s:                       │                              │ writes
   │ GET /StatusUpdate/              │                              │ currentStatus,
   ├────────────────────────────────>│                              │ timestamp
   │                                 │ session_status read          │
   │                                 │ time_of_last_status_check++  │
   │                                 │ save (with 100x retry)       │
   │<────────────────────────────────┤ JsonResponse(...)            │
   │                                 │                              │
   │ DOM updates in place            │                              │
   │                                 │                              │
   │     ... eventually ...          │                              │
   │                                 │                              │ writes
   │                                 │<─────────────────────────────┤ redirectToResultsFileOrURL
   │ GET /StatusUpdate/              │                              │
   ├────────────────────────────────>│                              │
   │<────────────────────────────────┤ {"completed": true}          │
   │                                 │                              │
   │ window.location = '/StatusAnd…' │                              │
   ├────────────────────────────────>│                              │
   │                                 │ existing completion branch:  │
   │                                 │ read+clear key, serve file   │
   │                                 │ OR HttpResponseRedirect      │
   │<────────────────────────────────┤                              │
```

JSON shape (in progress):

```json
{
  "completed": false,
  "currentStatus": "Created 5 of 12 Reports and Graphs<br><br>Currently using 3 parallel processes",
  "elapsed": "00:01:24",
  "serverTime": "Tue May 26 14:32:08",
  "lastUpdate": "Tue May 26 14:32:06",
  "loadavg": [0.42, 0.51, 0.45]
}
```

JSON shape (completion):

```json
{"completed": true}
```

`coreCount` is rendered once into the template from Python context (used for the load-legend sentence) and never polled — it doesn't change during a fit, so JS has no reason to touch that DOM element.

## Error handling

| Condition | Behavior |
|---|---|
| Session missing on `/StatusUpdate/` | `JsonResponse({"error": "no_session"}, status=400)`. JS treats any non-2xx as "wait and retry" — same as a network blip. |
| Required session keys missing (`currentStatus`/`start_time`/`timestamp`) | Same behavior as `StatusView` today: `JsonResponse({"error": "stale_session"}, status=400)` with the existing "delete the ZunZunNG cookie and try again" message. JS retries; the user eventually clears their cookie. |
| SQLite lock during `time_of_last_status_check` save | Existing 100×@10Hz retry loop, copy-pasted from `StatusView`. |
| `fetch` rejects (network drop, server restart) | Caught and ignored. Next 2s tick retries. No toast, no retry counter, no backoff. |
| Browser tab backgrounded | Modern browsers throttle `setInterval` in background tabs (typically to 1Hz). This is desirable: a backgrounded tab doesn't need 2s polls. The next foreground tick will reconcile. |

## Testing

**Unit tests in `tests/test_status_view.py`** (new file):
- `StatusView` renders the template (200, `Content-Type: text/html; charset=utf-8`) when session lacks `redirectToResultsFileOrURL`. Assert key DOM markers (`<h2>`, `id="currentStatus"`, the included `StatusPoll.js`).
- `StatusView` serves file body when `redirectToResultsFileOrURL` is a `TEMP_FILES_DIR` path. Assert response body matches the file. (Existing behavior; new test pinning it down.)
- `StatusView` returns `HttpResponseRedirect` when `redirectToResultsFileOrURL` is a site-relative URL. (Existing behavior; new test pinning it down.)
- `StatusView` clears `redirectToResultsFileOrURL` after consuming it. (Existing behavior; new test.)
- `StatusUpdateView` returns expected JSON shape when fit is in progress.
- `StatusUpdateView` returns `{"completed": true}` when `redirectToResultsFileOrURL` is set, and **does not clear it**.
- `StatusUpdateView` updates `time_of_last_status_check` on each call.
- `StatusUpdateView` returns 400 with `{"error": "no_session"}` when the session key is absent.
- `StatusUpdateView` returns 400 with `{"error": "stale_session"}` when required keys are missing.

**URL test** in `tests/test_urls.py`: add an assertion that `/StatusUpdate/` resolves to `zunzun.views.StatusUpdateView`.

**Smoke test** (`scripts/smoke_test.py`): no change. The smoke test polls `/StatusAndResults/` until the response body indicates completion. That URL still exists, still responds with the in-progress page (now HTML containing `id="currentStatus"`) or with the completion file/redirect. The smoke test's assertion strings ("polling for completion", recognizing the completion body) are checked once during implementation and updated only if the new template HTML breaks them; the goal is no functional change to the smoke contract.

**Manual browser check** during the implementation `verify` step: start runserver, kick off a 2D polynomial fit, watch the page update without a white flash, confirm completion navigates correctly. Repeat for a 3D fit (longer-running, more `currentStatus` transitions visible).

## Open questions / explicit decisions

- **Poll interval: 2 seconds.** Approved. Was 3s under meta-refresh; 2s feels live without being chatty.
- **Drop the 3-line load-average legend** in favor of a single sentence. Approved.
- **No rate-limit decorator on `StatusUpdateView`.** Heartbeat is its own throttle; `CommonToAllViews`'s 5-sec sleep on `request.limited` would specifically break polling.
- **`time_of_last_status_check` heartbeat moves from `StatusView` to `StatusUpdateView`.** This is the only behavioral change to the existing flow; both writes use the same SQLite-lock retry pattern.
- **Backwards compatibility:** none required. The status page has no callers outside the LRP redirect flow, and the smoke test asserts on completion-response body, not on the in-progress HTML structure.
