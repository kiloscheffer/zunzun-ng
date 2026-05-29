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
    #
    # Value is the float result of time.time() from the parent's
    # SetInitialStatusDataIntoSessionVariables. The float format is
    # load-bearing: equality comparisons against session.dispatched_at
    # appear in _we_own_status_slot (LRP method) and _run_fit_child
    # (this module). Two consecutive dispatches from the same user are
    # debounced by the per-user gate's 60s pending window, so
    # collisions on the float are not a practical risk.
    # 0.0 default exists for the dataclass; all production code paths
    # (every Fit*, CharacterizeData, StatisticalDistributions,
    # FunctionFinder, FunctionFinderResults) stamp a non-zero value.
    dispatch_id: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


def _setup_child_root_logging() -> None:
    """Install the per-pid FileHandler on the root logger.

    Called once at the top of every spawn child, before any
    ``_logger.debug(...)`` calls in ``PerformAllWork`` fire. Routes all
    propagated logging — including ``zunzun.LongRunningProcess.*``
    trace messages enabled via ``ZUNZUN_LRP_LOG_LEVEL=DEBUG`` — to
    ``temp/{pid}.log``.

    Without this early call, the per-pid file is only installed inside
    exception handlers (see the ``except`` branch below and the inline
    ``basicConfig`` calls elsewhere in the LRP tree), so DEBUG trace
    messages from normal flow are silently dropped — the
    ``ZUNZUN_LRP_LOG_LEVEL`` knob has no observable effect.

    Attaches the handler directly (not via ``logging.basicConfig``)
    for two reasons: ``basicConfig`` lowers the root logger's level
    when ``level=`` is passed, which would pull DEBUG/INFO messages
    from every other module (e.g. ``zunzun.parallel_pool``) into the
    per-pid file regardless of the env var; and ``basicConfig`` is a
    no-op when root already has any handler, so it would silently
    fail to install if some other code touched logging first. The
    direct ``addHandler`` call avoids both. Per-logger level filtering
    on ``zunzun.LongRunningProcess`` (from ``settings.LOGGING``)
    decides what reaches this handler.
    """
    import settings

    log_path = os.path.join(settings.TEMP_FILES_DIR, f"{os.getpid()}.log")
    root = logging.getLogger()
    # Idempotent: skip if a FileHandler for this exact path is already
    # attached. Identifying by baseFilename avoids duplicate handlers
    # if this function is somehow called twice.
    for h in root.handlers:
        if (
            isinstance(h, logging.FileHandler)
            and getattr(h, "baseFilename", None) == log_path
        ):
            return
    handler = logging.FileHandler(log_path)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(process)d %(name)s %(levelname)s %(message)s")
    )
    root.addHandler(handler)


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

    # Install the per-pid FileHandler BEFORE any LRP code runs, so
    # _logger.debug(...) trace messages from PerformAllWork actually
    # land in temp/{pid}.log when ZUNZUN_LRP_LOG_LEVEL=DEBUG is set.
    _setup_child_root_logging()

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
            # Ownership check gates BOTH the terminal-redirect write
            # AND the per-user gate clear. session.dispatched_at holds
            # the current dispatch's identity stamp; payload.dispatch_id
            # holds OUR dispatch's value. Equality means we are still
            # the current dispatch.
            #
            # session.dispatched_at is None means no dispatch has ever
            # claimed the slot — either the session was destroyed and
            # re-created mid-fit (key missing) or the very first fit's
            # SetInitial hasn't propagated yet. Treat as "we own" so
            # the terminal redirect still publishes in the rare
            # session-recreated case.
            #
            # Crucially, do NOT treat 0 / 0.0 as ours: those values
            # mean another fit explicitly cleared the slot
            # (PerformAllWork's finally, _publish_terminal_error's
            # bundled gate-clear, etc). If we're an older child whose
            # exception fires after a newer fit completed and cleared,
            # the slot's been released and we MUST NOT publish our
            # stale error redirect into it — StatusView would otherwise
            # serve our older error as the page for whichever fit
            # claims the slot next.
            #
            # Read failure defaults to "we own" — matches the defensive
            # default in _we_own_status_slot for the LRP-method sites.
            try:
                current_dispatch = lrp.LoadItemFromSessionStore("status", "dispatched_at")
            except Exception:
                _logging.exception("Could not read session dispatched_at; assuming we-own-slot")
                current_dispatch = payload.dispatch_id
            we_own_slot = current_dispatch == payload.dispatch_id or current_dispatch is None

            if not we_own_slot:
                _logging.info(
                    "Child exception; newer dispatch owns the slot; leaving session alone"
                )
            else:
                # Don't overwrite a redirect an earlier successful
                # stage already saved (e.g., RenderOutputHTML succeeded
                # then the success-path processID-cleanup in
                # PerformAllWork raised).
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
