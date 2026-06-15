"""Template context processors for the zunzun app.

Registered in settings.TEMPLATES[0]["OPTIONS"]["context_processors"], so every
key returned here is available in every template rendered via `render()`.
"""

import settings


def demo_mode(request):
    """Expose settings.DEMO_MODE to every template as `demo_mode`.

    Reads the *root* `settings` module (the project's no-inner-package layout —
    `import settings`), matching how zunzun.views reads DEMO_MODE and the
    concurrency caps. Tests therefore patch `settings.DEMO_MODE` directly rather
    than via Django's @override_settings, which patches the separate django.conf
    lazy wrapper this code never consults.
    """
    return {"demo_mode": settings.DEMO_MODE}


def head_html(request):
    """Expose settings.HEAD_HTML to every template as `head_html`.

    Operator-supplied raw markup injected at the top of <head> by
    generic_page_template.html; empty by default. Reads the root `settings`
    module directly (see the demo_mode docstring for why), so tests patch
    `settings.HEAD_HTML`, NOT Django's @override_settings.
    """
    return {"head_html": settings.HEAD_HTML}
