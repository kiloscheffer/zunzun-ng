"""Compact, sort-friendly identifier for one LRP child's artifacts.

Replaces the legacy ``'LRP_' + str(pid) + '_' + str(time.time()).replace('.', '_')``
pattern with a base36-packed form that keeps PID as a debugging breadcrumb
(correlates with ``{pid}.log``) but compresses the timestamp portion ~3x.

Format: ``zun_<pid_b36_4>_<ms_b36_8>`` — 13-char fixed-width payload.

Per-component artifacts (PNG, SVG, GIF) append ``_{anchor3}_{rank2}``
where ``anchor3`` is the 3-letter ``uniqueAnchorName`` set in
``ReportsAndGraphs.py`` and ``rank2`` is a 2-char base36 number
(covers 0..1295; FunctionFinder caps at ~1k ranked equations).
Ranks beyond 1295 produce a longer-than-2 chars suffix — fixed-width
breaks for those rows but no data is lost. Page-level artifacts (PDF,
result HTML) use the reserved anchor code ``zun`` and the placeholder
rank ``00`` so every artifact matches the same 5-segment shape.

Anchor namespace reservations:
  - ``zun`` is reserved for page-level artifacts (PDF, result HTML).
  - Any anchor starting with ``h`` is reserved for parametrized
    histogram instances (StatisticalDistributionHistogram uses
    ``h`` + 2-char base36 of distributionIndex; covers idx 0..1295).
    No other anchor may begin with ``h``.

Layout choices:
  - 20-bit PID field (4 base36 chars). Covers Linux raised-max
    ``pid_max`` (up to 2^22=4M with truncation) and Windows PIDs
    (commonly <100K) without aliasing in practice. ``pid & 0xFFFFF``
    keeps the field width consistent; values >1M alias but that's
    an upstream pid_max raise, not a realistic web-server config.
  - 41-bit ms field (8 base36 chars) measured from the 2026-01-01 UTC
    epoch. Range ≈ 70 years; saturates at the high end (clamp via
    ``max(_, 0)``) for the impossible case of a clock before the epoch.
"""

import os
import string
import time
from datetime import datetime, timezone

import settings


_BASE36 = string.digits + string.ascii_lowercase
_EPOCH_MS = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
# = 1_767_225_600_000

# Suffix attached to page-level artifacts (PDF, result HTML). The "zun"
# anchor code is reserved (see module docstring) and the "00" rank
# placeholder pads out to the same 5-segment shape as per-component
# artifacts. Defined once here so a future change to the convention
# lands in one place rather than 8+ callsites.
_PAGE_SUFFIX = "_zun_00"


def b36(n: int, width: int) -> str:
    """Format ``n`` as base36, zero-padded to at least ``width`` chars.

    Values that don't fit in ``width`` characters produce a longer
    string — the function never truncates. This means ``b36(0, 3)``
    returns ``"000"`` but ``b36(46656, 3)`` returns ``"1000"`` (4
    chars). Callers should size ``width`` to the expected maximum.
    """
    if n <= 0:
        return "0" * width
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = _BASE36[r] + out
    return out.rjust(width, "0")


def new_unique_string() -> str:
    pid_field = os.getpid() & 0xFFFFF
    ms_since_epoch = max(int(time.time() * 1000) - _EPOCH_MS, 0)
    return "zun_%s_%s" % (b36(pid_field, 4), b36(ms_since_epoch, 8))


def page_artifact_filename(unique_string: str, ext: str) -> str:
    """Bare filename of a page-level artifact (PDF or result HTML).

    Example: ``page_artifact_filename("zun_h5gz_05spf7rm", "pdf")``
    returns ``"zun_h5gz_05spf7rm_zun_00.pdf"``.

    Use when the consumer needs the bare name — e.g., setting
    ``self.pdfFileName`` for later joining with TEMP_FILES_DIR and
    for embedding in the ``/temp/{{ pdfFileName }}`` download link.
    For filesystem paths use ``page_artifact_path``; for site URLs
    use ``page_artifact_url``.
    """
    return unique_string + _PAGE_SUFFIX + "." + ext


def page_artifact_path(unique_string: str, ext: str) -> str:
    """Filesystem path of a page-level artifact under ``TEMP_FILES_DIR``."""
    return os.path.join(settings.TEMP_FILES_DIR, page_artifact_filename(unique_string, ext))


def page_artifact_url(unique_string: str, ext: str) -> str:
    """Site URL of a page-level artifact under ``MEDIA_URL``."""
    return settings.MEDIA_URL + page_artifact_filename(unique_string, ext)
