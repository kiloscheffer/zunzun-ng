"""Compact, sort-friendly identifier for one LRP child's artifacts.

Replaces the legacy ``'LRP_' + str(pid) + '_' + str(time.time()).replace('.', '_')``
pattern with a base36-packed form that keeps PID as a debugging breadcrumb
(correlates with ``{pid}.log``) but compresses the timestamp portion ~3x.

Format: ``zun_<pid_b36_3>_<ms_b36_8>`` — 12-char fixed-width payload.

Per-component artifacts (PNG, SVG, GIF) append ``_{anchor3}_{rank2}``
where ``anchor3`` is the 3-letter ``uniqueAnchorName`` set in
``ReportsAndGraphs.py``. Page-level artifacts (PDF, result HTML) use
the reserved anchor code ``zun`` and the placeholder rank ``00`` so
every artifact matches the same 5-segment shape. Anchor namespace:
``zun`` is reserved and MUST NOT be used as a per-component anchor.

Layout choices:
  - 15-bit PID field (3 base36 chars). Matches Linux default ``pid_max``
    of 32768 exactly. PIDs on raised-max Linux or Windows >32K are
    clipped via ``pid & 0x7FFF`` and may alias (rare enough to be useful
    as a coarse correlation key, not a unique key).
  - 41-bit ms field (8 base36 chars) measured from the 2026-01-01 UTC
    epoch. Range ≈ 70 years; saturates at the high end (clamp via
    ``max(_, 0)``) for the impossible case of a clock before the epoch.
"""

import os
import string
import time
from datetime import datetime, timezone


_BASE36 = string.digits + string.ascii_lowercase
_EPOCH_MS = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
# = 1_767_225_600_000


def _b36(n: int, width: int) -> str:
    if n <= 0:
        return "0" * width
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = _BASE36[r] + out
    return out.rjust(width, "0")


def new_unique_string() -> str:
    pid_field = os.getpid() & 0x7FFF
    ms_since_epoch = max(int(time.time() * 1000) - _EPOCH_MS, 0)
    return "zun_%s_%s" % (_b36(pid_field, 3), _b36(ms_since_epoch, 8))
