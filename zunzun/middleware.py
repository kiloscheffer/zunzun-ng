"""Project-wide middleware.

Replaces the historical pattern of calling
``CommonToAllViews(request)`` at the top of every view in
``zunzun/views.py``. The housekeeping that fired on every request —
zombie-child reap, IP block check, HTTP-method gate, rate-limit sleep
— now runs from a single registered middleware so new views pick it
up automatically.
"""

import time

from django import http

from zunzun import platform_compat


class CommonToAllViewsMiddleware:
    """Per-request cross-cutting work, applied to every view.

    Pre-view (runs before the view body):
      - Reap any completed multiprocessing children so they don't
        linger. No-op on Windows; proper cleanup on Unix.
      - Block requests by REMOTE_ADDR. The block list is currently
        empty; the hook is preserved for parity with the historical
        CommonToAllViews helper.
      - Reject any request method other than GET or POST with
        Http404.

    Post-view (runs after the view body returns):
      - If django-ratelimit's @ratelimit decorator marked the request
        as limited, sleep 5 s before sending the response. The sleep
        moved from "before view body" to "after view body" because
        the decorator only sets ``request.limited`` while the view is
        executing — middleware can't read it during process_request.
        Net effect on a slammer is unchanged (same total wall-clock
        latency); server CPU usage is also unchanged since the work
        runs either way.
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

        response = self.get_response(request)

        if getattr(request, "limited", False):
            time.sleep(5.0)

        return response
