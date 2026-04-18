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
