import os

from django.conf import settings
from django.conf.urls.static import static
from django.urls import re_path
from django.views.static import serve as static_serve

import zunzun.views

urlpatterns = [
    re_path(r"^$", zunzun.views.HomePageView),
    re_path(r"^StatusAndResults/", zunzun.views.StatusView),
    re_path(r"^StatusUpdate/", zunzun.views.StatusUpdateView),
    re_path(r"^CharacterizeData/([123])/$", zunzun.views.LongRunningProcessView),
    re_path(r"^StatisticalDistributions/([1])/$", zunzun.views.LongRunningProcessView),
    re_path(r"^FunctionFinder__.__/([23])/$", zunzun.views.LongRunningProcessView),
    re_path(r"^FunctionFinderResults/([23])/$", zunzun.views.LongRunningProcessView),
    re_path(r"^FitEquation__F__/([23])/(.+)/(.+)/$", zunzun.views.LongRunningProcessView),
    re_path(r"^Equation/([23])/(.+)/(.+)/$", zunzun.views.LongRunningProcessView),
    re_path(r"^EvaluateAtAPoint/$", zunzun.views.EvaluateAtAPointView),
    re_path(r"^AllEquations/([23])/(.+)/$", zunzun.views.AllEquationsView),
    re_path(r"^Feedback/$", zunzun.views.FeedbackView),
]

# Serve generated runtime files at MEDIA_URL in dev. In production,
# nginx/IIS serves /temp/ directly per docs/deployment/. STATIC_URL is
# auto-served by django.contrib.staticfiles during runserver.
#
# /CommonProblems/ serves the vendored CommonProblems static site
# (curve-fitting "common problems" reference content, originally at
# bitbucket.org/zunzuncode/CommonProblems and licensed under
# BSD-2-clause; preserved here as a permanent fork). Production
# deployments serve this directly via nginx/IIS per docs/deployment/.
# The bare-trailing-slash URL serves index.html explicitly because
# Django's static() helper doesn't auto-resolve directory→index.
if settings.DEBUG:
    # On-disk directory is lowercase (`commonproblems/`); URL is
    # case-sensitive `/CommonProblems/` per the Django routing default
    # and to match the upstream bitbucket repo's CapitalCase URL.
    _CP_DIR = os.path.join(settings.ROOT_PATH, "commonproblems")
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [
        re_path(
            r"^CommonProblems/$", static_serve, {"document_root": _CP_DIR, "path": "index.html"}
        ),
    ]
    urlpatterns += static("/CommonProblems/", document_root=_CP_DIR)
