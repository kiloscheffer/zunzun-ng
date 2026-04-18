import inspect, time, math, random, multiprocessing

import numpy, scipy, scipy.stats

from django.template.loader import render_to_string

from . import FittingBaseClass
from .StatusMonitoredLongRunningProcessPage import _json_native
from .child_payload import ChildPayload
import zunzun.forms



class FitSpline(FittingBaseClass.FittingBaseClass):

    def __init__(self):
        super().__init__()
        self.interfaceString = 'zunzun/equation_fit_interface.html'
        self.spline = True


    def SaveSpecificDataToSessionStore(self):
        # scipySpline is a tuple of numpy arrays; _json_native converts
        # the arrays to lists. The EvaluateAtAPointView will need to
        # reconstruct any spline-typed input from these raw sequences.
        self.SaveDictionaryOfItemsToSessionStore('data', _json_native({'dimensionality':self.dimensionality,
                                                          'equationName':self.inEquationName,
                                                          'equationFamilyName':self.inEquationFamilyName,
                                                          'scipySpline':self.dataObject.equation.scipySpline,
                                                          'solvedCoefficients':self.dataObject.equation.solvedCoefficients}))


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
        self.boundForm['fittingTarget'].required = False # not used in splines
        self.boundForm['splineSmoothness'].required = True # force form field validation
        self.boundForm['splineOrderX'].required = True # force form field validation
        if self.dimensionality == 3:
            self.boundForm['splineOrderY'].required = True # force form field validation
        
        
    def TransferFormDataToDataObject(self, request): # return any error in a user-viewable string (self.dataObject.ErrorString)
        s = FittingBaseClass.FittingBaseClass.TransferFormDataToDataObject(self, request)

        self.boundForm.equation.smoothingFactor = self.boundForm.cleaned_data['splineSmoothness']
        self.boundForm.equation.xOrder = int(self.boundForm.cleaned_data['splineOrderX'])
        if self.dimensionality == 3:
            self.boundForm.equation.yOrder = int(self.boundForm.cleaned_data['splineOrderY'])
        return s
