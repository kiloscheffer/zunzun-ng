import inspect, time, math, random, multiprocessing, os, sys, copy

import numpy, scipy, scipy.stats

import settings
from django.template.loader import render_to_string

from . import FittingBaseClass
from . import ReportsAndGraphs
from .StatusMonitoredLongRunningProcessPage import _json_native
from .child_payload import ChildPayload

import zunzun.forms
import pyeq3



class FitUserDefinedFunction(FittingBaseClass.FittingBaseClass):

    def __init__(self):
        super().__init__()
        self.interfaceString = 'zunzun/equation_fit_interface.html'
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
        self.SaveDictionaryOfItemsToSessionStore('data', _json_native({'dimensionality':self.dimensionality,
                                                          'equationName':self.inEquationName,
                                                          'equationFamilyName':self.inEquationFamilyName,
                                                          'solvedCoefficients':self.dataObject.equation.solvedCoefficients,
                                                          'udfEditor_' + str(self.dimensionality) + 'D':self.dataObject.equation.userDefinedFunctionText}))


    def TransferFormDataToDataObject(self, request): # return any error in a user-viewable string (self.dataObject.ErrorString)
        s = FittingBaseClass.FittingBaseClass.TransferFormDataToDataObject(self, request)
        self.boundForm.equation.fittingTarget = self.boundForm.cleaned_data['fittingTarget']
        return s


    def SpecificEquationUnboundInterfaceCode(self, request):
        self.unboundForm.fields['udfEditor'].initial = eval('zunzun.formConstants.initialUserDefinedFunctionText' + str(self.dimensionality) + 'D')
        if self.dimensionality == 2:
            self.dictionaryToReturn['udfFunctionsDict'] = pyeq3.Models_2D.UserDefinedFunction.UserDefinedFunction.functionDictionary
        else:
            self.dictionaryToReturn['udfFunctionsDict'] = pyeq3.Models_3D.UserDefinedFunction.UserDefinedFunction.functionDictionary


    def SpecificEquationBoundInterfaceCode(self, request):
        self.boundForm.equation.userDefinedFunctionText = request.POST['udfEditor']
        self.boundForm.equation.ParseAndCompileUserFunctionString(self.boundForm.equation.userDefinedFunctionText, self.dimensionality)

        
    def SpecificCodeForGeneratingListOfOutputReports(self):
        self.functionString = 'PrepareForReportOutput'
        self.SaveDictionaryOfItemsToSessionStore('status', {'currentStatus':"Calculating Error Statistics"})
        try:
            self.dataObject.CalculateErrorStatistics()
        except:
            itemsToRender = {}
            itemsToRender['error0'] = str(sys.exc_info()[0])
            itemsToRender['error1'] = str(sys.exc_info()[1])
            itemsToRender['extraText'] = 'Please check the text of your User Defined Function.'
            f = open(os.path.join(settings.TEMP_FILES_DIR, self.dataObject.uniqueString + "_zun_00.html"), "w")
            f.write(render_to_string('zunzun/exception_while_fitting_an_equation.html', itemsToRender))
            self.SaveDictionaryOfItemsToSessionStore('status', {'redirectToResultsFileOrURL':os.path.join(settings.TEMP_FILES_DIR, self.dataObject.uniqueString + "_zun_00.html")})
            # Raise SystemExit so the spawned child terminates cleanly without
            # overwriting the redirect already written to the session store.
            # SystemExit is a BaseException, not Exception, so the generic
            # "unknown exception" handler in _run_fit_child does not fire.
            # The finally block in _run_fit_child provides the post-work sleep.
            raise SystemExit(0)

        self.SaveDictionaryOfItemsToSessionStore('status', {'currentStatus':"Calculating Parameter Statistics"})
        self.dataObject.equation.CalculateCoefficientAndFitStatistics()

        self.SaveDictionaryOfItemsToSessionStore('status', {'currentStatus':"Generating Report Objects"})
        self.ReportsAndGraphsCategoryDict = ReportsAndGraphs.FittingReportsDict(self.dataObject)
