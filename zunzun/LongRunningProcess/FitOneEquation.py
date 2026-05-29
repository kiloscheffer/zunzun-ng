import copy
import inspect
import logging
import math
import multiprocessing
import os
import random
import sys
import time

import numpy
import scipy
import scipy.stats

import zunzun.forms

from . import FittingBaseClass

_logger = logging.getLogger(__name__)


class FitOneEquation(FittingBaseClass.FittingBaseClass):
    def __init__(self):
        super().__init__()
        self.interfaceString = "zunzun/equation_fit_interface.html"

    def SaveSpecificDataToSessionStore(self):
        self.SaveDictionaryOfItemsToSessionStore(
            "data",
            {
                "dimensionality": self.dimensionality,
                "equationName": self.inEquationName,
                "equationFamilyName": self.inEquationFamilyName,
                "solvedCoefficients": self.dataObject.equation.solvedCoefficients,
                "fittingTarget": self.dataObject.equation.fittingTarget,
                "logLinX": self.dataObject.logLinX,
                "logLinY": self.dataObject.logLinY,
            },
        )

    def TransferFormDataToDataObject(
        self, request
    ):  # return any error in a user-viewable string (self.dataObject.ErrorString)
        s = FittingBaseClass.FittingBaseClass.TransferFormDataToDataObject(self, request)
        self.boundForm.equation.fittingTarget = self.boundForm.cleaned_data["fittingTarget"]
        return s

    # This override allows form item preset when coming from the function finder
    def CreateUnboundInterfaceForm(self, request):
        dictionaryToReturn = super().CreateUnboundInterfaceForm(request)

        if self.dimensionality == 2:
            try:
                logLinX = self.LoadItemFromSessionStore("data", "logLinX")
                logLinY = self.LoadItemFromSessionStore("data", "logLinY")
                _logger.debug("1 logLinX:" + str(logLinX) + " logLinY: " + str(logLinY))
            except:
                logLinX = "LIN"
                logLinY = "LIN"

            if logLinX != "LIN" and logLinX != "LOG":
                logLinX = "LIN"
                logLinY = "LIN"
            if logLinY != "LIN" and logLinY != "LOG":
                logLinY = "LIN"
                logLinY = "LIN"

            _logger.debug("1 logLinX:" + str(logLinX) + " logLinY: " + str(logLinY))

            self.unboundForm.fields["logLinX"].initial = logLinX
            self.unboundForm.fields["logLinY"].initial = logLinY

        return dictionaryToReturn
