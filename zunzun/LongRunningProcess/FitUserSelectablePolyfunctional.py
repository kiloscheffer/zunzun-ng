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
        self.boundForm.equation.polyfunctional2DFlags = []
        self.boundForm.equation.polyfunctional3DFlags = []

        if self.dimensionality == 2:
            for i in range(len(self.X2DList)):
                self.boundForm[
                    "polyFunctional_X" + str(i)
                ].required = True  # force form field validation
                if request.POST["polyFunctional_X" + str(i)] == "True":
                    self.boundForm.equation.polyfunctional2DFlags.append(i)
        else:  # 3D
            for i in range(len(self.X3DList)):
                for j in range(len(self.Y3DList)):
                    self.boundForm[
                        "polyFunctional_X" + str(i) + "Y" + str(j)
                    ].required = True  # force form field validation
                    if request.POST["polyFunctional_X" + str(i) + "Y" + str(j)] == "True":
                        self.boundForm.equation.polyfunctional3DFlags.append([i, j])

    def SpecificEquationUnboundInterfaceCode(self, request):

        if self.rank:
            self.equation.polyfunctional2DFlags = self.functionFinderResultsList[self.rank - 1][4]
            self.equation.polyfunctional3DFlags = self.functionFinderResultsList[self.rank - 1][5]
            if self.dimensionality == 2:
                flags = self.functionFinderResultsList[self.rank - 1][4]
                self.dictionaryToReturn["Polyfun2DColorList"] = self._build_2d_color_list(
                    lambda i: i in flags
                )
            else:  # 3D
                flags = self.functionFinderResultsList[self.rank - 1][5]
                self.dictionaryToReturn["Polyfun3DColorList"] = self._build_3d_color_list(
                    lambda i, j: [i, j] in flags
                )
        else:
            if self.dimensionality == 2:
                self.dictionaryToReturn["Polyfun2DColorList"] = self._build_2d_color_list(
                    lambda i: False
                )
            else:  # 3D
                self.dictionaryToReturn["Polyfun3DColorList"] = self._build_3d_color_list(
                    lambda i, j: False
                )
        FittingBaseClass.FittingBaseClass.SpecificEquationUnboundInterfaceCode(self, request)
