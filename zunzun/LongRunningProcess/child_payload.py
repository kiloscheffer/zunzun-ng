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
    # dispatch_id is the unique identifier for THIS dispatch — the
    # parent stamps it into both the payload AND the session in
    # SetInitialStatusDataIntoSessionVariables. The exception handler
    # in _run_fit_child compares its payload's value against the
    # current session value to detect "a newer fit replaced me",
    # avoiding races where an older failing child publishes its
    # terminal redirect into a newer fit's shared status session.
    # Currently the value is float seconds (time.time()) for
    # convenience — microsecond resolution is unique enough that two
    # consecutive dispatches will never collide given Python overhead.
    # Stored as float and compared with equality; 0.0 means "no
    # dispatch identifier was stamped" (legacy / FunctionFinderResults
    # paths that haven't been updated).
    dispatch_id: float = 0.0
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
            # Single ownership check gates BOTH the terminal-redirect
            # write AND the per-user gate clear. Uses dispatch_id (a
            # timestamp stamped by the parent's
            # SetInitialStatusDataIntoSessionVariables into both the
            # payload and the session) as the dispatch identity.
            #
            # With ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=True (default),
            # multiple POSTs reuse session_key_status. A naïve processID
            # check is racy because:
            #   - A newer fit's SetInitial clears the redirect AND
            #     overwrites dispatched_at, but does NOT touch the older
            #     child's processID. So the older child's pid-equality
            #     check would still match and it would publish its
            #     terminal redirect into the newer fit's shared session.
            #   - Conversely, during the window between a newer parent's
            #     SetInitial and its child's first processID write, the
            #     session can show an older child's pid even though the
            #     dispatch has moved on.
            #
            # Comparing dispatch_id resolves both: each dispatch has a
            # unique microsecond-precision timestamp. session.dispatched_at
            # holds the current dispatch's value; payload.dispatch_id
            # holds OUR dispatch's value. Equality means "we are still
            # the current dispatch."
            #
            # Backward-compat: payload.dispatch_id == 0.0 means the
            # payload was built before this contract existed (no current
            # code paths). Fall back to the older pid-based check.
            we_own_slot = False
            if payload.dispatch_id != 0.0:
                try:
                    current_dispatch = lrp.LoadItemFromSessionStore("status", "dispatched_at")
                except Exception:
                    _logging.exception("Could not read session dispatched_at; assuming we-own-slot")
                    current_dispatch = payload.dispatch_id
                # current_dispatch in (None, 0, 0.0) means no dispatch
                # is currently claiming the slot — either session expired
                # mid-fit and was re-created, or PerformAllWork's finally
                # already cleared it. Treat as "we own" so the terminal
                # redirect still publishes; if a NEWER dispatch claimed
                # the slot, current_dispatch would be a positive float
                # different from ours and the check below would correctly
                # mark us not-owners. Mirrors the legacy pid-fallback
                # below which treats current_pid in (None, 0) as owned.
                we_own_slot = current_dispatch == payload.dispatch_id or current_dispatch in (
                    None,
                    0,
                    0.0,
                )
            else:
                try:
                    current_pid = lrp.LoadItemFromSessionStore("status", "processID")
                except Exception:
                    _logging.exception("Could not read processID; assuming we-own-slot")
                    current_pid = None
                we_own_slot = current_pid in (None, 0) or current_pid == os.getpid()

            if not we_own_slot:
                _logging.info(
                    "Child exception; newer dispatch owns the slot; leaving session alone"
                )
            else:
                # Don't overwrite a redirect an earlier successful stage
                # already saved (e.g., RenderOutputHTML succeeded then
                # the processID-cleanup at line 779 raised).
                existing_redirect = ""
                try:
                    existing_redirect = (
                        lrp.LoadItemFromSessionStore("status", "redirectToResultsFileOrURL") or ""
                    )
                except Exception:
                    _logging.exception("Could not read existing redirect; assuming none")

                # Bundle redirect/status + gate-clear into ONE atomic
                # SaveDictionaryOfItemsToSessionStore call. Previous
                # code did two separate saves with a race window in
                # between, during which a newer fit could write its
                # own processID/dispatched_at — the second clear save
                # would then wipe the newer fit's tracking.
                payload_dict: dict[str, Any] = {"processID": 0, "dispatched_at": 0}
                if not existing_redirect:
                    payload_dict["currentStatus"] = (
                        "An unknown exception has occurred, and an email with "
                        "details has been sent to the site administrator."
                    )
                    if write_succeeded:
                        payload_dict["redirectToResultsFileOrURL"] = error_html_path
                else:
                    _logging.info(
                        "Exception after redirect already set; preserving existing: %s",
                        existing_redirect,
                    )
                lrp.SaveDictionaryOfItemsToSessionStore("status", payload_dict)
        except Exception:
            _logging.exception("Also failed to write terminal error status after child exception")
    finally:
        time.sleep(1.0)  # match the existing post-work sleep
        # Child returns (implicit); multiprocessing handles exit code.
