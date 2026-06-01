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


class FitUserCustomizablePolynomial(FittingBaseClass.FittingBaseClass):
    def __init__(self):
        super().__init__()
        self.interfaceString = "zunzun/equation_fit_interface.html"
        self.X2DList = pyeq3.PolyFunctions.GenerateListForCustomPolynomials_2D()

    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["polynomial2DFlags"] = self.boundForm.equation.polynomial2DFlags
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.dataObject.equation.polynomial2DFlags = payload.extra["polynomial2DFlags"]

    def SaveSpecificDataToSessionStore(self):
        self.SaveDictionaryOfItemsToSessionStore(
            "data",
            {
                "dimensionality": self.dimensionality,
                "equationName": self.inEquationName,
                "equationFamilyName": self.inEquationFamilyName,
                "solvedCoefficients": self.dataObject.equation.solvedCoefficients,
                "fittingTarget": self.dataObject.equation.fittingTarget,
                "polynomial2DFlags": self.dataObject.equation.polynomial2DFlags,
            },
        )

    def TransferFormDataToDataObject(
        self, request
    ):  # return any error in a user-viewable string (self.dataObject.ErrorString)
        s = FittingBaseClass.FittingBaseClass.TransferFormDataToDataObject(self, request)
        self.boundForm.equation.fittingTarget = self.boundForm.cleaned_data["fittingTarget"]
        return s

    def SpecificEquationBoundInterfaceCode(self, request):
        # _collect_2d_picker_flags setattrs polynomial2DFlags before returning,
        # so no pre-init is needed; this class carries only the 2D flag list.
        self._collect_2d_picker_flags(request, "polynomial2DFlags")

    def SpecificEquationUnboundInterfaceCode(self, request):
        self._assign_2d_picker_color_list("Polynomial2DColorList", "polynomial2DFlags")
        FittingBaseClass.FittingBaseClass.SpecificEquationUnboundInterfaceCode(self, request)
