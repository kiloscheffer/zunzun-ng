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
    /* currentStatus contains server-assembled HTML (<br>, <b>, <table>) written
     * only by trusted LRP code in zunzun/LongRunningProcess/. No user-supplied
     * text is interpolated into this string. innerHTML is safe here. */
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
