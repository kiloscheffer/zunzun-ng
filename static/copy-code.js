(function () {
  if (!navigator.clipboard) return;

  const COPY = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  const CHECK = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>';

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("pre").forEach(function (pre) {
      const btn = document.createElement("button");

      btn.type = "button";
      btn.className = "copy-btn";
      btn.innerHTML = COPY;
      btn.setAttribute("aria-label", "Copy code to clipboard");

      btn.addEventListener("click", function () {
        navigator.clipboard
          .writeText(pre.textContent)
          .then(function () {
            btn.innerHTML = CHECK;
            btn.setAttribute("aria-label", "Copied");
            setTimeout(function () {
              btn.innerHTML = COPY;
              btn.setAttribute("aria-label", "Copy code to clipboard");
            }, 1500);
          })
          .catch(function () {
            /* clipboard denied -- leave the icon alone */
          });
      });

      pre.appendChild(btn);
    });
  });
})();
