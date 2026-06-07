import inspect
import math
import multiprocessing
import random
import time

import numpy
import scipy
import scipy.stats
from django.template.loader import render_to_string

import zunzun.forms

from . import FittingBaseClass
from .child_payload import ChildPayload


class FitSpline(FittingBaseClass.FittingBaseClass):
    def __init__(self):
        super().__init__()
        self.interfaceString = "zunzun/equation_fit_interface.html"
        self.spline = True

    def SaveSpecificDataToSessionStore(self):
        # scipySpline is a live scipy.interpolate.UnivariateSpline (2D) or
        # SmoothBivariateSpline (3D) instance — not JSON-serializable.
        # Storing it here crashes the session save. The object is
        # redundant: solvedCoefficients holds the spline's tck tuple (see
        # pyeq3/Services/SolverService.py SolveUsingSpline — 2D _eval_args,
        # 3D .tck). pyeq3's Spline.RebuildScipySpline rebuilds a callable
        # spline from that tck on demand; EvaluateAtAPointView triggers it
        # via CalculateModelPredictions at the load site.
        #
        # 3D needs one extra piece: scipy's BivariateSpline.tck is the
        # 3-tuple (tx, ty, c) and does NOT carry the spline degrees — those
        # live in scipySpline.degrees == (kx, ky). RebuildScipySpline reads
        # them from the equation's xOrder/yOrder, so we persist them
        # separately and the view assigns them back before the rebuild. (2D's
        # _eval_args already bundles the degree as its third element, so 2D
        # needs nothing extra.)
        items = {
            "dimensionality": self.dimensionality,
            "equationName": self.inEquationName,
            "equationFamilyName": self.inEquationFamilyName,
            "solvedCoefficients": self.dataObject.equation.solvedCoefficients,
        }
        if self.dimensionality == 3:
            items["splineDegrees"] = [
                self.dataObject.equation.xOrder,
                self.dataObject.equation.yOrder,
            ]
        self.SaveDictionaryOfItemsToSessionStore("data", items)

    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["smoothingFactor"] = self.boundForm.equation.smoothingFactor
        payload.extra["xOrder"] = self.boundForm.equation.xOrder
        if self.dimensionality == 3:
            payload.extra["yOrder"] = self.boundForm.equation.yOrder
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.dataObject.equation.smoothingFactor = payload.extra["smoothingFactor"]
        self.dataObject.equation.xOrder = payload.extra["xOrder"]
        if self.dimensionality == 3:
            self.dataObject.equation.yOrder = payload.extra["yOrder"]

    def SpecificEquationBoundInterfaceCode(self, request):
        self.boundForm["fittingTarget"].required = False  # not used in splines
        self.boundForm["splineSmoothness"].required = True  # force form field validation
        self.boundForm["splineOrderX"].required = True  # force form field validation
        if self.dimensionality == 3:
            self.boundForm["splineOrderY"].required = True  # force form field validation

    def TransferFormDataToDataObject(
        self, request
    ):  # return any error in a user-viewable string (self.dataObject.ErrorString)
        s = FittingBaseClass.FittingBaseClass.TransferFormDataToDataObject(self, request)

        self.boundForm.equation.smoothingFactor = self.boundForm.cleaned_data["splineSmoothness"]
        self.boundForm.equation.xOrder = int(self.boundForm.cleaned_data["splineOrderX"])
        if self.dimensionality == 3:
            self.boundForm.equation.yOrder = int(self.boundForm.cleaned_data["splineOrderY"])
        return s
