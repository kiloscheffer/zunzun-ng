"""URL resolution tests.

Asserts every public route in urls.py resolves to the correct view
callable. Regression catcher for the Phase 5 urls.py rewrite.
"""
import pytest
from django.urls import resolve

import zunzun.views


@pytest.mark.parametrize("path,view_fn", [
    ("/", zunzun.views.HomePageView),
    ("/StatusAndResults/", zunzun.views.StatusView),
    ("/CharacterizeData/2/", zunzun.views.LongRunningProcessView),
    ("/StatisticalDistributions/1/", zunzun.views.LongRunningProcessView),
    ("/FunctionFinder__F__/2/", zunzun.views.LongRunningProcessView),
    ("/FunctionFinderResults/2/", zunzun.views.LongRunningProcessView),
    ("/FitEquation__F__/2/Polynomial/Quadratic/", zunzun.views.LongRunningProcessView),
    ("/Equation/2/Polynomial/Quadratic/", zunzun.views.LongRunningProcessView),
    ("/EvaluateAtAPoint/", zunzun.views.EvaluateAtAPointView),
    ("/AllEquations/2/Polynomial/", zunzun.views.AllEquationsView),
    ("/Feedback/", zunzun.views.FeedbackView),
])
def test_url_resolves_to_view(path, view_fn):
    match = resolve(path)
    assert match.func is view_fn, f"{path} resolved to {match.func}, expected {view_fn}"
