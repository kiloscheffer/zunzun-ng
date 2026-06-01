import copy
import inspect
import math
import multiprocessing
import os
import random
import sys
import time

import numpy
import pyeq3
import scipy
import scipy.stats

import zunzun.formConstants
import zunzun.forms

from . import FittingBaseClass
from .child_payload import ChildPayload


class FitUserSelectablePolyfunctional(FittingBaseClass.FittingBaseClass):
    def __init__(self):
        super().__init__()
        self.interfaceString = "zunzun/equation_fit_interface.html"
        self.X2DList = pyeq3.PolyFunctions.GenerateListForPolyfunctionals_2D()
        self.X3DList = pyeq3.PolyFunctions.GenerateListForPolyfunctionals_3D_X()
        self.Y3DList = pyeq3.PolyFunctions.GenerateListForPolyfunctionals_3D_Y()

    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["polyfunctional2DFlags"] = self.boundForm.equation.polyfunctional2DFlags
        payload.extra["polyfunctional3DFlags"] = self.boundForm.equation.polyfunctional3DFlags
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.dataObject.equation.polyfunctional2DFlags = payload.extra["polyfunctional2DFlags"]
        self.dataObject.equation.polyfunctional3DFlags = payload.extra["polyfunctional3DFlags"]

    def SaveSpecificDataToSessionStore(self):
        self.SaveDictionaryOfItemsToSessionStore(
            "data",
            {
                "dimensionality": self.dimensionality,
                "equationName": self.inEquationName,
                "equationFamilyName": self.inEquationFamilyName,
                "solvedCoefficients": self.dataObject.equation.solvedCoefficients,
                "fittingTarget": self.dataObject.equation.fittingTarget,
                "polyfunctional2DFlags": self.dataObject.equation.polyfunctional2DFlags,
                "polyfunctional3DFlags": self.dataObject.equation.polyfunctional3DFlags,
            },
        )

    def TransferFormDataToDataObject(
        self, request
    ):  # return any error in a user-viewable string (self.dataObject.ErrorString)
        s = FittingBaseClass.FittingBaseClass.TransferFormDataToDataObject(self, request)
        self.boundForm.equation.fittingTarget = self.boundForm.cleaned_data["fittingTarget"]
        return s

    def SpecificEquationBoundInterfaceCode(self, request):
        # build_child_payload carries BOTH flag lists across the spawn boundary,
        # so the inactive dimension must exist as []; only the active dimension's
        # list is populated by the _collect_* helper below.
        self.boundForm.equation.polyfunctional2DFlags = []
        self.boundForm.equation.polyfunctional3DFlags = []
        if self.dimensionality == 2:
            self._collect_2d_picker_flags(request, "polyfunctional2DFlags")
        else:
            self._collect_3d_picker_flags(request, "polyfunctional3DFlags")

    def SpecificEquationUnboundInterfaceCode(self, request):
        if self.dimensionality == 2:
            self._assign_2d_picker_color_list("Polyfun2DColorList", "polyfunctional2DFlags")
        else:
            self._assign_3d_picker_color_list("Polyfun3DColorList", "polyfunctional3DFlags")
        FittingBaseClass.FittingBaseClass.SpecificEquationUnboundInterfaceCode(self, request)
