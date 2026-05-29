"""SQLite-aware retry helpers for the Django session backend.

Spawn-child contention on the SQLite session DB is common in this
codebase — each request's child interpreter calls ``session.save()``
during fit dispatch and status updates, and multiple children writing
to the same SQLite file can briefly raise ``OperationalError``
("database is locked"). The 100-retry @ 10Hz pattern below has been
the established workaround since the original ``os.fork()`` era; this
module centralises it so new save / load sites are obviously correct
(``save_with_retry(s)`` is hard to typo) and the
``fork-pattern-reviewer`` agent's check simplifies to "every session
save is a ``save_with_retry`` call."
"""

from __future__ import annotations

import time
from typing import Any


def save_with_retry(session, *, max_retries: int = 100, delay: float = 0.1) -> None:
    """Save a Django SessionStore, retrying on transient errors.

    Loops up to ``max_retries`` times, sleeping ``delay`` seconds
    between attempts (defaults give 100 retries @ 10 Hz = 10 s total
    budget). Catches Exception broadly to match the historical loop
    shape — narrowing to ``OperationalError`` / ``InterfaceError``
    would be cleaner, but risks regressing on edge cases that the
    decade-old broad ``except`` quietly handled (e.g. transient
    ``ProgrammingError`` from a connection that closed mid-save).
    """
    retries = 0
    while True:
        try:
            session.save()
            return
        except Exception:
            retries += 1
            if retries > max_retries:
                raise
            time.sleep(delay)


def load_with_retry(
    session,
    key: str,
    *,
    max_retries: int = 100,
    delay: float = 0.1,
    default: Any = None,
) -> Any:
    """Read a key from a Django SessionStore, retrying on transient errors.

    Mirrors ``save_with_retry``: SQLite contention can affect reads
    too, not just writes. Missing keys return ``default`` (None by
    default) immediately without retrying — only transient
    ``DatabaseError`` / ``InterfaceError`` from the SQLite backend
    trigger a retry. Other exceptions propagate.

    Pairs with the defensive "default to we-own-slot on read failure"
    in ``StatusMonitoredLongRunningProcessPage._we_own_status_slot``:
    that helper's catch is now a last-resort net, since the underlying
    load retries before raising. The defensive default still matters
    for the rare exhausted-retries case.
    """
    from django.db import DatabaseError, InterfaceError

    retries = 0
    while True:
        try:
            return session[key]
        except KeyError:
            return default
        except (DatabaseError, InterfaceError):  # fmt: skip
            # ruff format would drop the parens — the result parses
            # as a Tuple expression and behaves identically, but reads
            # like Python 2's `except X, varname:` syntax. Keep parens
            # for readability.
            retries += 1
            if retries > max_retries:
                raise
            time.sleep(delay)
