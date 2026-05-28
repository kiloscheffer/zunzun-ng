"""Spawn-safe payload for multiprocessing.Process handoff.

The LongRunningProcessView used to call os.fork() which inherited the
parent's full memory, including non-picklable objects like the bound
Django Form. multiprocessing.Process(spawn) requires everything passed
to the child to be picklable. ChildPayload carries only the primitives
and pickle-safe objects the child needs to reconstruct an LRP instance
and run PerformAllWork().
"""

from __future__ import annotations

import importlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass
class ChildPayload:
    """Picklable snapshot of the state PerformAllWork() needs.

    lrp_class_path: dotted module path, e.g.
      "zunzun.LongRunningProcess.FitOneEquation.FitOneEquation".
      The child uses importlib + getattr to resurrect the LRP class,
      then hydrates fields from this payload.
    session_key_*: Django SessionStore keys (strings).
    dimensionality: 1, 2, or 3.
    renice_level: Unix nice value to apply via platform_compat.
    data_object: the existing DataObject attr-bag; already picklable.
    equation: pyeq3 equation instance (picklability verified in
      tests/test_pickle_spike.py).
    extra: subclass-specific fields. Each Fit* subclass extends this
      dict with its flags (spline order, polynomial flags, etc.).
    """

    lrp_class_path: str
    session_key_status: str
    session_key_data: str
    session_key_functionfinder: str
    dimensionality: int
    renice_level: int
    data_object: Any
    equation: Any
    extra: dict[str, Any] = field(default_factory=dict)


def _run_fit_child(payload: ChildPayload) -> None:
    """Entrypoint function for multiprocessing.Process(target=...).

    Executes in the spawned child process. Reconstructs an LRP
    instance from the payload, runs PerformAllWork(), then returns.

    Any uncaught exception is logged to temp/{pid}.log (matching the
    existing logging pattern in views.LongRunningProcessView) before
    the child exits.
    """
    # Spawn starts a fresh Python interpreter — it does not inherit the
    # parent's Django bootstrap. Without this setup, any ORM access
    # (e.g. SessionStore save) raises AppRegistryNotReady.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
    import django

    django.setup()

    from zunzun import platform_compat

    # Apply nice level to the child process itself
    try:
        platform_compat.set_process_niceness(os.getpid(), payload.renice_level)
    except Exception as e:  # noqa: BLE001 — defensive; niceness is best-effort
        _logger.info("Child process could not renice: %s", e)

    # Resolve the LRP class
    module_path, _, class_name = payload.lrp_class_path.rpartition(".")
    module = importlib.import_module(module_path)
    lrp_class = getattr(module, class_name)

    # Reconstruct the LRP. Both hydration AND PerformAllWork live
    # inside the try so failures in either path still produce a
    # terminal redirect. Set the session keys directly from payload
    # BEFORE calling apply_child_payload — the except-branch's
    # SaveDictionaryOfItemsToSessionStore depends on session_key_status
    # being on the instance, and we cannot rely on subclass overrides
    # always calling super().apply_child_payload() before their own
    # logic (the base apply_child_payload sets these keys, but a
    # subclass that validates payload.extra first would raise before
    # super() ran, leaving session_key_status unset).
    lrp = lrp_class()
    lrp.session_key_status = payload.session_key_status
    lrp.session_key_data = payload.session_key_data
    lrp.session_key_functionfinder = payload.session_key_functionfinder

    try:
        lrp.apply_child_payload(payload)
        lrp.PerformAllWork()
    except Exception:
        import logging as _logging

        from django.template.loader import render_to_string

        import settings

        log_path = os.path.join(settings.TEMP_FILES_DIR, f"{os.getpid()}.log")
        _logging.basicConfig(filename=log_path, level=_logging.DEBUG)
        _logging.exception("Child exception in _run_fit_child")

        # Write a terminal error artifact so the polling UI completes.
        # Without this, StatusUpdateView keeps reporting completed=False
        # forever because no redirectToResultsFileOrURL is ever set, and
        # the user is stuck on the status page until the session expires.
        # Mirrors the three-layer fallback in
        # RenderOutputHTMLToAFileAndSetStatusRedirect: try the Django
        # template first, fall back to a hardcoded HTML string if
        # render_to_string raises (template loader broken). The hardcoded
        # fallback only fails if disk itself is unwritable.
        error_html_path = os.path.join(settings.TEMP_FILES_DIR, f"error_{os.getpid()}.html")
        write_succeeded = False
        try:
            with open(error_html_path, "w", encoding="utf-8") as f:
                f.write(
                    render_to_string(
                        "zunzun/generic_error.html",
                        {
                            "error": "An unknown exception occurred while processing your "
                            "request. The site administrator has been notified."
                        },
                    )
                )
            write_succeeded = True
        except Exception:
            _logging.exception("Failed to render generic_error.html; trying static fallback")
            try:
                with open(error_html_path, "w", encoding="utf-8") as f:
                    f.write(
                        "<html><head><title>ZunZunNG - Error</title></head>"
                        "<body><h2>Error</h2>"
                        "<p>An unknown exception occurred while processing your "
                        "request. The site administrator has been notified.</p>"
                        "</body></html>"
                    )
                write_succeeded = True
            except Exception:
                _logging.exception("Also failed to write static fallback HTML")

        try:
            # Don't overwrite a redirect an earlier successful stage
            # already saved. PerformAllWork can succeed all the way
            # through RenderOutputHTMLToAFileAndSetStatusRedirect (which
            # sets the success redirect) and THEN raise in the
            # processID-cleanup at line 779 if that LoadItemFromSessionStore
            # hits a transient SQLite error. Without this guard we'd
            # clobber the success-results redirect with our error page
            # even though the result HTML is on disk and ready to serve.
            existing_redirect = ""
            try:
                existing_redirect = (
                    lrp.LoadItemFromSessionStore("status", "redirectToResultsFileOrURL") or ""
                )
            except Exception:
                _logging.exception("Could not read existing redirect; assuming none")

            if not existing_redirect:
                payload_dict = {
                    "currentStatus": "An unknown exception has occurred, and an email with "
                    "details has been sent to the site administrator."
                }
                if write_succeeded:
                    payload_dict["redirectToResultsFileOrURL"] = error_html_path
                lrp.SaveDictionaryOfItemsToSessionStore("status", payload_dict)
            else:
                _logging.info(
                    "Exception after redirect already set; preserving existing: %s",
                    existing_redirect,
                )

            # Clear the per-user gate so the user can immediately retry.
            # Safe-to-clear cases:
            #   - processID is None   → first-fit session, never written
            #   - processID is 0      → previous fit cleared cleanly
            #   - processID == ours   → we own the slot (PerformAllWork
            #                           wrote it before failing)
            # Don't clear if some OTHER pid owns it — that means a
            # concurrent fit under ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=True
            # claimed the slot, and clobbering its tracking would confuse
            # the gate and the status page.
            try:
                current_pid = lrp.LoadItemFromSessionStore("status", "processID")
                if current_pid in (None, 0) or current_pid == os.getpid():
                    lrp.SaveDictionaryOfItemsToSessionStore(
                        "status", {"processID": 0, "dispatched_at": 0}
                    )
            except Exception:
                _logging.exception("Could not conditionally clear per-user gate")
        except Exception:
            _logging.exception("Also failed to write terminal error status after child exception")
    finally:
        time.sleep(1.0)  # match the existing post-work sleep
        # Child returns (implicit); multiprocessing handles exit code.
