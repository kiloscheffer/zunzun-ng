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
from django.template.loader import render_to_string

import settings
import zunzun.forms

from . import FittingBaseClass, ReportsAndGraphs
from ._unique import page_artifact_path
from .child_payload import ChildPayload
from .StatusMonitoredLongRunningProcessPage import _json_native


class FitUserDefinedFunction(FittingBaseClass.FittingBaseClass):
    def __init__(self):
        super().__init__()
        self.interfaceString = "zunzun/equation_fit_interface.html"
        self.userDefinedFunction = True
        self.reniceLevel = 15

    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["userDefinedFunctionText"] = self.boundForm.equation.userDefinedFunctionText
        # ParseAndCompileUserFunctionString (called during form validation
        # to verify the formula compiles) leaves a compiled code object on
        # the equation at .userFunctionCodeObject. Code objects are not
        # picklable, so multiprocessing.Popen's spawn handoff would raise
        # TypeError("cannot pickle code objects"). Drop it here; the child
        # re-parses in apply_child_payload to reconstruct the code object.
        if hasattr(payload.equation, "userFunctionCodeObject"):
            del payload.equation.userFunctionCodeObject
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        text = payload.extra["userDefinedFunctionText"]
        self.dataObject.equation.userDefinedFunctionText = text
        # Re-parse in the child to recreate userFunctionCodeObject (dropped
        # at the pickle boundary — see build_child_payload).
        self.dataObject.equation.ParseAndCompileUserFunctionString(text, payload.dimensionality)

    def SaveSpecificDataToSessionStore(self):
        self.SaveDictionaryOfItemsToSessionStore(
            "data",
            _json_native(
                {
                    "dimensionality": self.dimensionality,
                    "equationName": self.inEquationName,
                    "equationFamilyName": self.inEquationFamilyName,
                    "solvedCoefficients": self.dataObject.equation.solvedCoefficients,
                    "udfEditor_"
                    + str(self.dimensionality)
                    + "D": self.dataObject.equation.userDefinedFunctionText,
                }
            ),
        )

    def TransferFormDataToDataObject(
        self, request
    ):  # return any error in a user-viewable string (self.dataObject.ErrorString)
        s = FittingBaseClass.FittingBaseClass.TransferFormDataToDataObject(self, request)
        self.boundForm.equation.fittingTarget = self.boundForm.cleaned_data["fittingTarget"]
        return s

    def SpecificEquationUnboundInterfaceCode(self, request):
        self.unboundForm.fields["udfEditor"].initial = eval(
            "zunzun.formConstants.initialUserDefinedFunctionText" + str(self.dimensionality) + "D"
        )
        if self.dimensionality == 2:
            self.dictionaryToReturn["udfFunctionsDict"] = (
                pyeq3.Models_2D.UserDefinedFunction.UserDefinedFunction.functionDictionary
            )
        else:
            self.dictionaryToReturn["udfFunctionsDict"] = (
                pyeq3.Models_3D.UserDefinedFunction.UserDefinedFunction.functionDictionary
            )

    def SpecificEquationBoundInterfaceCode(self, request):
        self.boundForm.equation.userDefinedFunctionText = request.POST["udfEditor"]
        self.boundForm.equation.ParseAndCompileUserFunctionString(
            self.boundForm.equation.userDefinedFunctionText, self.dimensionality
        )

    def SpecificCodeForGeneratingListOfOutputReports(self):
        self.functionString = "PrepareForReportOutput"
        self.SaveDictionaryOfItemsToSessionStore(
            "status", {"currentStatus": "Calculating Error Statistics"}
        )
        try:
            self.dataObject.CalculateErrorStatistics()
        except:
            itemsToRender = {}
            itemsToRender["error0"] = str(sys.exc_info()[0])
            itemsToRender["error1"] = str(sys.exc_info()[1])
            itemsToRender["extraText"] = "Please check the text of your User Defined Function."
            error_html_path = page_artifact_path(self.dataObject.uniqueString, "html")
            # encoding="utf-8" matches StatusView's reader and the other
            # terminal-redirect writers. Without it, Windows defaulted
            # to cp1252 and non-ASCII content in a UDF traceback would
            # be re-decoded incorrectly by StatusView. The previous open()
            # also leaked the file handle (no close, no with-block).
            with open(error_html_path, "w", encoding="utf-8") as f:
                f.write(
                    render_to_string(
                        "zunzun/exception_while_fitting_an_equation.html", itemsToRender
                    )
                )
            self.SaveDictionaryOfItemsToSessionStore(
                "status", {"redirectToResultsFileOrURL": error_html_path}
            )
            # Clear the per-user gate before terminating. SystemExit
            # bypasses _run_fit_child's exception handler (which catches
            # Exception, not BaseException), so its ownership-verified
            # gate-clear at the end of the except branch never runs.
            # Dual condition (pid AND dispatched_at must both match)
            # avoids clobbering a concurrent newer fit's dispatch
            # markers — a newer fit's SetInitial overwrites session
            # dispatched_at without touching processID, and a pid-only
            # check would then erase the newer fit's tracking.
            if self.LoadItemFromSessionStore(
                "status", "processID"
            ) == os.getpid() and self.LoadItemFromSessionStore(
                "status", "dispatched_at"
            ) == getattr(self, "dispatched_at", None):
                self.SaveDictionaryOfItemsToSessionStore(
                    "status", {"processID": 0, "dispatched_at": 0}
                )
            # Raise SystemExit so the spawned child terminates cleanly without
            # overwriting the redirect already written to the session store.
            # SystemExit is a BaseException, not Exception, so the generic
            # "unknown exception" handler in _run_fit_child does not fire.
            # The finally block in _run_fit_child provides the post-work sleep.
            raise SystemExit(0)

        self.SaveDictionaryOfItemsToSessionStore(
            "status", {"currentStatus": "Calculating Parameter Statistics"}
        )
        self.dataObject.equation.CalculateCoefficientAndFitStatistics()

        self.SaveDictionaryOfItemsToSessionStore(
            "status", {"currentStatus": "Generating Report Objects"}
        )
        self.ReportsAndGraphsCategoryDict = ReportsAndGraphs.FittingReportsDict(self.dataObject)
