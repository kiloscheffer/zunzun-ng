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

    # Reconstruct the LRP. The subclass is responsible for populating
    # itself from the payload via apply_child_payload().
    lrp = lrp_class()
    lrp.apply_child_payload(payload)

    try:
        lrp.PerformAllWork()
    except Exception:
        import settings
        import logging as _logging
        log_path = os.path.join(settings.TEMP_FILES_DIR, f"{os.getpid()}.log")
        _logging.basicConfig(filename=log_path, level=_logging.DEBUG)
        _logging.exception("Child exception in _run_fit_child")

        try:
            lrp.SaveDictionaryOfItemsToSessionStore(
                "status",
                {"currentStatus":
                    "An unknown exception has occurred, and an email with "
                    "details has been sent to the site administrator."}
            )
        except Exception:
            _logging.exception("Also failed to write status after child exception")
    finally:
        time.sleep(1.0)  # match the existing post-work sleep
        # Child returns (implicit); multiprocessing handles exit code.
