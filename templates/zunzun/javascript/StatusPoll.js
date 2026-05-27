/* StatusPoll.js — polls /StatusUpdate/ every 2 seconds and updates the
 * status page DOM in place. On completion, navigates to /StatusAndResults/
 * which re-enters StatusView's completion branch (file body or redirect).
 *
 * Failure tolerance: any fetch/parse exception is swallowed; the next
 * 2-second tick retries. At 2s intervals a missed poll is invisible.
 */
(function () {
  var POLL_INTERVAL_MS = 2000;
  var intervalId = null;
  var inFlight = false;

  function applyUpdate(data) {
    if (data.completed === true) {
      /* Stop polling before navigating so the loop doesn't fire spurious
       * fetches during the navigation transition and on the next page. */
      if (intervalId !== null) {
        clearInterval(intervalId);
        intervalId = null;
      }
      window.location.assign('/StatusAndResults/');
      return;
    }
    /* currentStatus contains server-assembled HTML (<br>, <b>, <table>) written
     * only by trusted LRP code in zunzun/LongRunningProcess/. No user-supplied
     * text is interpolated into this string. innerHTML is safe here. */
    var statusEl = document.getElementById('currentStatus');
    if (statusEl) statusEl.innerHTML = data.currentStatus;

    setText('elapsedTime', data.elapsed);

    /* parallelProcessCount is shown inline only during the parallel
     * reports phase; suppressed otherwise to avoid flickering. */
    var ppi = document.getElementById('parallelProcessInfo');
    if (ppi) {
      if (data.parallelProcessCount && data.parallelProcessCount > 1) {
        ppi.textContent = ' · ' + data.parallelProcessCount + ' parallel processes';
      } else {
        ppi.textContent = '';
      }
    }

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
    /* In-flight guard: under SQLite contention the heartbeat-write retry
     * loop on the server can take longer than the poll interval. Skip
     * the new tick rather than letting fetches overlap (which would
     * apply DOM updates out of order and double-bump the heartbeat). */
    if (inFlight) return;
    inFlight = true;
    fetch('/StatusUpdate/', { credentials: 'same-origin' })
      .then(function (response) {
        if (!response.ok) return;  /* 4xx/5xx: retry next tick */
        return response.json();
      })
      .then(function (data) {
        if (data) applyUpdate(data);
      })
      .catch(function () { /* network blip: swallow, retry next tick */ })
      .finally(function () { inFlight = false; });
  }

  /* First poll fires immediately to refresh between initial render and JS load. */
  poll();
  intervalId = setInterval(poll, POLL_INTERVAL_MS);
})();
