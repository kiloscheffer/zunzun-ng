/* ServerLoadPoll.js — keeps the home page "Server Load" panel live.
 *
 * The home page is @cache_page-cached for an hour (and emits a matching
 * max-age browser cache), so any load-average value baked into its HTML
 * would freeze. server_load.html therefore renders placeholders; this
 * poller fills #hpLoad1/#hpLoad5/#hpLoad15 from /ServerLoad/, a no-cache
 * JSON endpoint, so the numbers are current rather than a stale snapshot.
 *
 * The panel (#serverloadDiv) is hidden by default and revealed by the
 * "Site Related → Server Load" dropdown. We only fetch while it is visible
 * to avoid hammering the endpoint for every home-page visitor, and fire an
 * immediate poll when it is opened so the placeholders fill without waiting
 * a full interval.
 *
 * Like StatusPoll.js, this is spliced into a <head> <script> via
 * generic_page_template.html's additional_javascript block, so it self-defers
 * to DOMContentLoaded — #serverloadDiv does not exist during head parsing.
 */
(function () {
  var POLL_INTERVAL_MS = 5000;
  var inFlight = false;

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  /* Pad to two decimals so 2 and an unrounded 2.12060546875 both display as
   * "2.00"/"2.12" (Alpine/musl's getloadavg returns unrounded fixed-point;
   * glibc/Windows round to 2). */
  function fmtLoad(n) {
    var x = Number(n);
    return isFinite(x) ? x.toFixed(2) : n;
  }

  function panelVisible() {
    var el = document.getElementById('serverloadDiv');
    return !!el && !el.classList.contains('hidden');
  }

  function poll() {
    /* Skip work while the panel is hidden, and never overlap fetches. */
    if (inFlight || !panelVisible()) return;
    inFlight = true;
    fetch('/ServerLoad/', { credentials: 'same-origin' })
      .then(function (response) {
        if (!response.ok) return null;  /* 4xx/5xx: retry next tick */
        return response.json();
      })
      .then(function (data) {
        if (data && data.loadavg && data.loadavg.length === 3) {
          setText('hpLoad1', fmtLoad(data.loadavg[0]));
          setText('hpLoad5', fmtLoad(data.loadavg[1]));
          setText('hpLoad15', fmtLoad(data.loadavg[2]));
        }
      })
      .catch(function () { /* network blip: swallow, retry next tick */ })
      .finally(function () { inFlight = false; });
  }

  function start() {
    /* Fire as soon as the panel is opened. The dropdown's change handler
     * (f4) toggles #serverloadDiv.hidden; defer one tick so it runs first,
     * then poll() sees the panel as visible. */
    var sel = document.getElementById('s4');
    if (sel) {
      sel.addEventListener('change', function () { setTimeout(poll, 0); });
    }
    poll();
    setInterval(poll, POLL_INTERVAL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
