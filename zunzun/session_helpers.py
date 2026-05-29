"""Session-backend helpers for the Django session store.

Two concerns live here, both about the SQLite-backed Django session:

1. **SQLite-contention retry** (``save_with_retry`` / ``load_with_retry``).
   Spawn-child contention on the SQLite session DB is common in this
   codebase — each request's child interpreter calls ``session.save()``
   during fit dispatch and status updates, and multiple children writing
   to the same SQLite file can briefly raise ``OperationalError``
   ("database is locked"). The 100-retry @ 10Hz pattern has been the
   established workaround since the original ``os.fork()`` era;
   centralising it means new save / load sites are obviously correct
   (``save_with_retry(s)`` is hard to typo) and the
   ``fork-pattern-reviewer`` agent's check simplifies to "every session
   save is a ``save_with_retry`` call."

2. **numpy-aware JSON serialization** (``NumpyJSONEncoder`` /
   ``NumpySessionSerializer``). pyeq3 produces numpy scalars and arrays
   (coefficient arrays, ranking tuples) that Django's default
   ``JSONSerializer`` can't encode. ``NumpySessionSerializer`` is wired
   in via ``settings.SESSION_SERIALIZER`` so the coercion happens
   automatically at ``session.save()`` time — no per-call-site
   ``_json_native(...)`` wrapper to remember.
"""

from __future__ import annotations

import json
import time
from typing import Any

from django.contrib.sessions.serializers import JSONSerializer


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


class NumpyJSONEncoder(json.JSONEncoder):
    """json.JSONEncoder that coerces numpy leaves to Python primitives.

    Only the two cases that ``json`` itself can't handle need an override:

      - ``numpy.ndarray`` -> ``list`` (via ``.tolist()``)
      - ``numpy.generic`` (int64/int32/bool_/etc.) -> Python scalar
        (via ``.item()``)

    Note ``numpy.float64`` is a subclass of ``float`` and serializes
    natively, so it never reaches ``default()`` — which is fine, it
    round-trips to a Python float either way. ``json`` already recurses
    into dicts / lists / tuples natively and only calls ``default()`` on
    the leaves it can't encode, so no recursive container walk is needed
    here (unlike the old ``_json_native`` helper this replaces).

    numpy is imported lazily so this module stays importable in any
    context that doesn't actually serialize numpy (it's pulled in via
    ``settings.SESSION_SERIALIZER`` and touched on every session save).
    """

    def default(self, o: Any) -> Any:
        import numpy

        if isinstance(o, numpy.ndarray):
            return o.tolist()
        if isinstance(o, numpy.generic):
            return o.item()
        return super().default(o)


class NumpySessionSerializer(JSONSerializer):
    """Session serializer that routes encoding through ``NumpyJSONEncoder``.

    Wired in via ``settings.SESSION_SERIALIZER``. Matches Django's stock
    ``JSONSerializer.dumps`` byte-for-byte (same ``separators`` and
    latin-1 encoding) except for the ``cls=`` encoder, so existing
    session blobs stay compatible. ``loads`` is inherited unchanged —
    decoding is plain ``json.loads`` and produces the same Python
    primitives regardless of how they were encoded.
    """

    def dumps(self, obj: Any) -> bytes:
        return json.dumps(obj, separators=(",", ":"), cls=NumpyJSONEncoder).encode("latin-1")
