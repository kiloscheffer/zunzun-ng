"""Django app config for zunzun.

Uses AppConfig.ready() to check for required external binaries
(mogrify, gifsicle) on startup and log a prominent warning if
they're missing. Fits still work without them; 3D animations do not.
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
                "Fits will work, but animated GIF output will fail. "
                "Install with: apt-get install imagemagick gifsicle (Linux), "
                "brew install imagemagick gifsicle (macOS), or "
                "winget install ImageMagick.ImageMagick and winget install gifsicle.gifsicle (Windows).",
                ", ".join(missing),
            )
