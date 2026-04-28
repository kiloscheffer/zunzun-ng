import os

from django.conf import settings
from django.conf.urls.static import static
from django.urls import re_path
import zunzun.views

urlpatterns = [
    re_path(r"^$", zunzun.views.HomePageView),
    re_path(r"^StatusAndResults/", zunzun.views.StatusView),
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
# /commonproblems/ serves the vendored CommonProblems static site
# (curve-fitting "common problems" reference content, originally at
# bitbucket.org/zunzuncode/commonproblems and licensed under
# BSD-2-clause; preserved here as a permanent fork). Production
# deployments serve this directly via nginx/IIS per docs/deployment/.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static('/commonproblems/', document_root=os.path.join(settings.ROOT_PATH, 'commonproblems'))
