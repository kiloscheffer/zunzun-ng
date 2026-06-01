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


class FitUserSelectableRational(FittingBaseClass.FittingBaseClass):
    def __init__(self):
        super().__init__()
        self.interfaceString = "zunzun/equation_fit_interface.html"
        self.reniceLevel = 13
        self.X2DList = pyeq3.PolyFunctions.GenerateListForRationals_2D()

    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["rationalNumeratorFlags"] = self.boundForm.equation.rationalNumeratorFlags
        payload.extra["rationalDenominatorFlags"] = self.boundForm.equation.rationalDenominatorFlags
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.dataObject.equation.rationalNumeratorFlags = payload.extra["rationalNumeratorFlags"]
        self.dataObject.equation.rationalDenominatorFlags = payload.extra[
            "rationalDenominatorFlags"
        ]

    def SaveSpecificDataToSessionStore(self):
        self.SaveDictionaryOfItemsToSessionStore(
            "data",
            {
                "dimensionality": self.dimensionality,
                "equationName": self.inEquationName,
                "equationFamilyName": self.inEquationFamilyName,
                "solvedCoefficients": self.dataObject.equation.solvedCoefficients,
                "fittingTarget": self.dataObject.equation.fittingTarget,
                "rationalNumeratorFlags": self.dataObject.equation.rationalNumeratorFlags,
                "rationalDenominatorFlags": self.dataObject.equation.rationalDenominatorFlags,
            },
        )

    def TransferFormDataToDataObject(
        self, request
    ):  # return any error in a user-viewable string (self.dataObject.ErrorString)
        s = FittingBaseClass.FittingBaseClass.TransferFormDataToDataObject(self, request)
        self.boundForm.equation.fittingTarget = self.boundForm.cleaned_data["fittingTarget"]
        return s

    def SpecificEquationBoundInterfaceCode(self, request):
        if self.dimensionality == 2:
            for i in range(len(self.X2DList)):
                self.boundForm[
                    "polyRational_X_N" + str(i)
                ].required = True  # force form field validation
                self.boundForm[
                    "polyRational_X_D" + str(i)
                ].required = True  # force form field validation

            self.boundForm["polyRational_OFFSET"].required = True  # force form field validation
            self.boundForm.equation.rationalNumeratorFlags = []
            self.boundForm.equation.rationalDenominatorFlags = []
            for i in range(len(self.X2DList)):
                if request.POST["polyRational_X_N" + str(i)] == "True":
                    self.boundForm.equation.rationalNumeratorFlags.append(i)
                if request.POST["polyRational_X_D" + str(i)] == "True":
                    self.boundForm.equation.rationalDenominatorFlags.append(i)

    def SpecificEquationUnboundInterfaceCode(self, request):
        # Unlike the polyfunctional / customizable-polynomial pickers, rational
        # can't reuse _assign_2d_picker_color_list: it reads two FF result
        # indices ([8] numerator / [9] denominator) into two dict keys and
        # derives the offset flag from the coefficient count ([11]). But the
        # per-cell loop is exactly FittingBaseClass._build_2d_color_list, so the
        # numerator/denominator lists fold onto it while the offset/index logic
        # stays here.
        if self.rank:  # coming from a Function Finder
            self.equation.solvedCoefficients = self.functionFinderResultsList[self.rank - 1][11]
            self.equation.rationalNumeratorFlags = self.functionFinderResultsList[self.rank - 1][8]
            self.equation.rationalDenominatorFlags = self.functionFinderResultsList[self.rank - 1][
                9
            ]
            numeratorFlags = self.equation.rationalNumeratorFlags
            denominatorFlags = self.equation.rationalDenominatorFlags
            self.dictionaryToReturn["Polyrat2DNumeratorColorList"] = self._build_2d_color_list(
                lambda i: i in numeratorFlags
            )
            self.dictionaryToReturn["Polyrat2DDenominatorColorList"] = self._build_2d_color_list(
                lambda i: i in denominatorFlags
            )
            if len(self.equation.solvedCoefficients) == len(numeratorFlags) + len(denominatorFlags):
                self.dictionaryToReturn["offsetSelected"] = False  # Offset Term NOT used
            else:
                self.dictionaryToReturn["offsetSelected"] = True  # Offset Term used
        else:  # NOT coming from a function finder
            self.dictionaryToReturn["Polyrat2DNumeratorColorList"] = self._build_2d_color_list(
                lambda i: False
            )
            self.dictionaryToReturn["Polyrat2DDenominatorColorList"] = self._build_2d_color_list(
                lambda i: False
            )
            self.dictionaryToReturn["offsetSelected"] = False  # Offset Term
        FittingBaseClass.FittingBaseClass.SpecificEquationUnboundInterfaceCode(self, request)
