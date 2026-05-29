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
    session_key_data: str
    session_key_functionfinder: str
    dimensionality: int
    renice_level: int
    data_object: Any
    equation: Any
    # status_row_pk is the LRPStatus row pk this dispatch writes to.
    # The parent creates the row in views.LongRunningProcessView at
    # dispatch time and stamps its pk here; the child uses it for every
    # update_status call and in the terminal-error handler below. Each
    # dispatch owns its own row, so there is no ownership check — a
    # newer dispatch has its own row, and an update against a
    # deleted/superseded pk matches zero rows (harmless).
    # 0 default exists for the dataclass; all production code paths set
    # a real pk via build_child_payload from self.status_row_pk.
    status_row_pk: int = 0
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
        if isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == log_path:
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
    # terminal redirect. Set the session keys + status_row_pk directly
    # from payload BEFORE calling apply_child_payload, since a subclass
    # override that validates payload.extra first could raise before
    # super().apply_child_payload() runs. The except-branch's terminal
    # write below addresses the LRPStatus row by payload.status_row_pk
    # directly, so it does not depend on apply_child_payload having run.
    lrp = lrp_class()
    lrp.session_key_data = payload.session_key_data
    lrp.session_key_functionfinder = payload.session_key_functionfinder
    lrp.status_row_pk = payload.status_row_pk

    try:
        lrp.apply_child_payload(payload)
        lrp.PerformAllWork()
    except Exception:
        import logging as _logging

        from django.template.loader import render_to_string

        import settings

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
            # Publish the terminal redirect to THIS dispatch's row. No
            # ownership check: a newer dispatch has its own row, and if
            # it deleted ours the update matches zero rows (harmless).
            from zunzun.models import LRPStatus

            # Don't clobber a redirect an earlier successful stage
            # already set (e.g., RenderOutputHTML succeeded then the
            # success-path process_id-cleanup raised).
            existing = (
                LRPStatus.objects.filter(pk=payload.status_row_pk)
                .values_list("redirect_to_results", flat=True)
                .first()
            )
            update_fields: dict[str, Any] = {"process_id": 0}
            if not existing:
                update_fields["redirect_to_results"] = error_html_path if write_succeeded else ""
                update_fields["current_status"] = (
                    "An unknown exception has occurred, and an email with "
                    "details has been sent to the site administrator."
                )
            LRPStatus.objects.filter(pk=payload.status_row_pk).update(**update_fields)
        except Exception:
            _logging.exception("Also failed to write terminal error status after child exception")
    finally:
        time.sleep(1.0)  # match the existing post-work sleep
        # Child returns (implicit); multiprocessing handles exit code.
