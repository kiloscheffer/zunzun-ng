"""Project-wide middleware and shared view decorators.

Replaces the historical pattern of calling
``CommonToAllViews(request)`` at the top of every view in
``zunzun/views.py``. The housekeeping that fired on every request —
zombie-child reap, IP block check, HTTP-method gate — now runs from a
single registered middleware so new views pick it up automatically.
The rate-limit sleep lives in the ``rate_limit_sleep`` decorator
applied alongside ``@ratelimit`` (see docstring there for why).
"""

import functools
import time

from django import http

from zunzun import platform_compat


class CommonToAllViewsMiddleware:
    """Per-request cross-cutting work, applied to every view.

    Runs before the view body:
      - Reap any completed multiprocessing children so they don't
        linger. No-op on Windows; proper cleanup on Unix.
      - Block requests by REMOTE_ADDR. The block list is currently
        empty; the hook is preserved for parity with the historical
        CommonToAllViews helper.
      - Reject any request method other than GET or POST with
        Http404.

    The rate-limit sleep used to live here, but moved into the
    ``rate_limit_sleep`` decorator below so it runs *before* the view
    body (preserving the slammer back-pressure on expensive paths
    like the fit-child spawn in ``LongRunningProcessView``).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        platform_compat.reap_completed_children()

        ip = request.META.get("REMOTE_ADDR")
        if ip in []:
            raise http.Http404

        if request.META["REQUEST_METHOD"] not in ["GET", "POST"]:
            raise http.Http404

        return self.get_response(request)


def rate_limit_sleep(view_func):
    """Sleep 5 s when ``request.limited`` is set, before the view runs.

    Apply *below* ``@ratelimit`` so that decorator stack order makes
    @ratelimit run first (setting ``request.limited``), then this
    decorator reads the flag and sleeps, then the view body executes.
    This is what preserves slammer back-pressure on expensive view
    paths: a rate-limited POST to ``LongRunningProcessView`` waits the
    5 s before spawning the fit child, so a flood of requests can't
    instantly spawn a corresponding flood of children.

    The sleep can't live in middleware because django-ratelimit's
    ``@ratelimit`` decorator only sets ``request.limited`` while
    the view is being called — middleware ``process_request`` runs
    too early; middleware ``process_response`` runs too late (work
    already happened).
    """

    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if getattr(request, "limited", False):
            time.sleep(5.0)
        return view_func(request, *args, **kwargs)

    return wrapper
