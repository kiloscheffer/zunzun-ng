import inspect, time, math, random, multiprocessing, os, sys, copy

import numpy, scipy, scipy.stats

from . import FittingBaseClass
from .StatusMonitoredLongRunningProcessPage import _json_native
import zunzun.forms

from . import pid_trace



class FitOneEquation(FittingBaseClass.FittingBaseClass):

    def __init__(self):
        super().__init__()
        self.interfaceString = 'zunzun/equation_fit_interface.html'


    def SaveSpecificDataToSessionStore(self):
        self.SaveDictionaryOfItemsToSessionStore('data', _json_native({'dimensionality':self.dimensionality,
                                                          'equationName':self.inEquationName,
                                                          'equationFamilyName':self.inEquationFamilyName,
                                                          'solvedCoefficients':self.dataObject.equation.solvedCoefficients,
                                                          'fittingTarget':self.dataObject.equation.fittingTarget,
                                                          'logLinX':self.dataObject.logLinX,
                                                          'logLinY':self.dataObject.logLinY}))


    def TransferFormDataToDataObject(self, request): # return any error in a user-viewable string (self.dataObject.ErrorString)
        s = FittingBaseClass.FittingBaseClass.TransferFormDataToDataObject(self, request)
        self.boundForm.equation.fittingTarget = self.boundForm.cleaned_data['fittingTarget']
        return s


    # This override allows form item preset when coming from the function finder
    def CreateUnboundInterfaceForm(self, request):
        dictionaryToReturn = super().CreateUnboundInterfaceForm(request)

        if self.dimensionality == 2:
            try:
                logLinX = self.LoadItemFromSessionStore('data', 'logLinX')
                logLinY = self.LoadItemFromSessionStore('data', 'logLinY')
                pid_trace.pid_trace('1 logLinX:' + str(logLinX) + ' logLinY: ' + str(logLinY))
            except:
                logLinX = 'LIN'
                logLinY = 'LIN'

            if logLinX != 'LIN' and logLinX != 'LOG':
                logLinX = 'LIN'
                logLinY = 'LIN'                
            if logLinY != 'LIN' and logLinY != 'LOG':
                logLinY = 'LIN'
                logLinY = 'LIN'
                
            pid_trace.pid_trace('1 logLinX:' + str(logLinX) + ' logLinY: ' + str(logLinY))
                
            self.unboundForm.fields['logLinX'].initial = logLinX
            self.unboundForm.fields['logLinY'].initial = logLinY
            
            pid_trace.delete_pid_trace_file()
        
        return dictionaryToReturn
