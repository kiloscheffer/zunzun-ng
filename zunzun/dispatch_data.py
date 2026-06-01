"""Read/write helpers for the per-dispatch LRPDispatchData row.

Replaces the per-session `data`/`functionfinder` SessionStores. Keyed by the
dispatch's LRPStatus pk (LRPDispatchData is OneToOne to LRPStatus). Writes go
through the same SQLite-contention retry idiom as session_helpers, because the
row is written by spawn children that contend on the SQLite file.
"""

from __future__ import annotations

import time
from typing import Any

from django.db import OperationalError

_FIELDS = ("data", "functionfinder")


def _retry(fn, *, max_retries: int = 100, delay: float = 0.1):
    retries = 0
    while True:
        try:
            return fn()
        except OperationalError:
            retries += 1
            if retries > max_retries:
                raise
            time.sleep(delay)


def save_items(status_pk: int, field: str, items: dict[str, Any]) -> None:
    """Merge `items` into the named JSON field of the dispatch's data row."""
    assert field in _FIELDS
    from zunzun.models import LRPDispatchData

    def _do():
        obj, _ = LRPDispatchData.objects.get_or_create(status_id=status_pk)
        current = getattr(obj, field) or {}
        current.update(items)
        setattr(obj, field, current)
        obj.save(update_fields=[field])

    _retry(_do)


def load_item(status_pk: int, field: str, key: str, *, default: Any = None) -> Any:
    """Read one key from the named JSON field of the dispatch's data row."""
    assert field in _FIELDS
    from zunzun.models import LRPDispatchData

    def _do():
        obj = LRPDispatchData.objects.filter(status_id=status_pk).first()
        if obj is None:
            return default
        return (getattr(obj, field) or {}).get(key, default)

    return _retry(_do)
