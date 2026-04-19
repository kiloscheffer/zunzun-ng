"""Django app config for zunzun.

Uses AppConfig.ready() to log a startup warning if any required
external binaries are missing from PATH. As of 2026-04-19 the
codebase has no non-Python runtime binary dependencies; the hook
is retained for future platform-specific checks.
"""
import logging

from django.apps import AppConfig

_logger = logging.getLogger(__name__)


class ZunZunConfig(AppConfig):
    name = "zunzun"

    def ready(self) -> None:
        from . import platform_compat
        missing = platform_compat.ensure_external_binaries()
        if missing:
            _logger.warning(
                "zunzunsite3: missing external binaries on PATH: %s. "
                "Install the missing binaries via your platform's package manager.",
                ", ".join(missing),
            )
