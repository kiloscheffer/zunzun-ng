import inspect
import io
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

import zunzun.forms

from . import ReportsAndGraphs, StatusMonitoredLongRunningProcessPage, pid_trace
from .child_payload import ChildPayload


def parallelWorkFunction(distributionName, data, sortCriteriaName):
    try:
        #pid_trace.pid_trace('distro: ' + distributionName)
        #tstart = time.time()
        r = pyeq3.Services.SolverService.SolverService().SolveStatisticalDistribution(distributionName, data, sortCriteriaName)
        #tend = time.time()
        #pid_trace.pid_trace('elapsed time ' + str(int(tend - tstart)) + ' seconds')
        return r
    except:
        return 0


class StatisticalDistributions(StatusMonitoredLongRunningProcessPage.StatusMonitoredLongRunningProcessPage):

    def __init__(self):
        super().__init__()
        self.parallelWorkItemsList = []

        self.interfaceString = 'zunzun/characterize_data_or_statistical_distributions_interface.html'
        self.equationName = None
        self.statisticalDistribution = True
        self.webFormName = 'Statistical Distributions'
        self.reniceLevel = 12
        self.characterizerOutputTrueOrReportOutputFalse = True
        self.evaluateAtAPointFormNeeded = False

    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra['pdfTitleHTML'] = self.pdfTitleHTML
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.pdfTitleHTML = payload.extra['pdfTitleHTML']

    def TransferFormDataToDataObject(self, request): # return any error in a user-viewable string (self.dataObject.ErrorString)
        pid_trace.pid_trace()

        self.pdfTitleHTML = self.webFormName + ' ' + str(self.dimensionality) + 'D'
        self.CommonCreateAndInitializeDataObject(False)
        self.dataObject.equation = self.boundForm.equationBase
        self.dataObject.equation._name = 'undefined' # the EquationBaseClass itself has no equation name
        self.dataObject.textDataEditor = self.boundForm.cleaned_data["textDataEditor"]
        self.dataObject.statisticalDistributionsSortBy = self.boundForm.cleaned_data['statisticalDistributionsSortBy']
        return ''


    def GenerateListOfWorkItems(self):

        pid_trace.pid_trace()

        self.SaveDictionaryOfItemsToSessionStore('status', {'currentStatus':"Sorting Data"})

        # required for special beta distribution data max/min case
        self.dataObject.IndependentDataArray[0].sort()

        self.SaveDictionaryOfItemsToSessionStore('status', {'currentStatus':"Generating List Of Work Items"})
        for item in inspect.getmembers(scipy.stats): # weibull max and min are duplicates of Frechet distributions
            if isinstance(item[1], scipy.stats.rv_continuous) and item[0] not in ['kstwobign', 'ncf', 'levy_stable']: # these are very slow, taking too long
                self.parallelWorkItemsList.append(item[0])

        pid_trace.pid_trace()


    def PerformWorkInParallel(self):
        pid_trace.pid_trace()

        countOfWorkItemsRun = 0
        totalNumberOfWorkItemsToBeRun = len(self.parallelWorkItemsList)

        begin = -self.parallelChunkSize
        end = 0
        indices = []

        chunks = totalNumberOfWorkItemsToBeRun // self.parallelChunkSize
        modulus = totalNumberOfWorkItemsToBeRun % self.parallelChunkSize

        for i in range(chunks):
            begin += self.parallelChunkSize
            end += self.parallelChunkSize
            indices.append([begin, end])

        if modulus:
            indices.append([end, end + 1 + modulus])

        # sort order here
        calculateCriteriaForUseInListSorting = 'nnlf'
        if 'AIC' == self.dataObject.statisticalDistributionsSortBy:
            calculateCriteriaForUseInListSorting = 'AIC'
        if 'AICc_BA' == self.dataObject.statisticalDistributionsSortBy:
            calculateCriteriaForUseInListSorting = 'AICc_BA'

        for i in indices:
            parallelChunkResultsList = []
            self.pool = multiprocessing.Pool(self.GetParallelProcessCount())

            for item in self.parallelWorkItemsList[i[0]:i[1]]:
                parallelChunkResultsList.append(self.pool.apply_async(parallelWorkFunction, (item, self.dataObject.IndependentDataArray[0], calculateCriteriaForUseInListSorting)))

            for r in parallelChunkResultsList:
                returnedValue = r.get()
                if not returnedValue:
                    continue
                countOfWorkItemsRun += 1
                self.completedWorkItemsList.append(returnedValue)
                self.WorkItems_CheckOneSecondSessionUpdates(countOfWorkItemsRun, totalNumberOfWorkItemsToBeRun)

            self.pool.close()
            self.pool.join()
            self.pool = None

        # final save is outside the 'one second updates'. Clearing
        # parallelProcessCount drops the indicator now that no pool is active.
        self.SaveDictionaryOfItemsToSessionStore('status', {
            'currentStatus': "Fitted %s of %s Statistical Distributions" % (countOfWorkItemsRun, totalNumberOfWorkItemsToBeRun),
            'parallelProcessCount': 0,
        })

        for i in self.completedWorkItemsList:

            distro = getattr(scipy.stats, i[1]['distributionName']) # convert distro name back into a distribution object
            # dig out a long name. scipy's names and doc strings
            # are irregular, so dig lfrom the scipy.stats.__doc__ text
            # if present there.
            tempString = None
            lines = io.StringIO(scipy.stats.__doc__).readlines()
            for line in lines:
                if -1 != line.find('  ' + i[1]['distributionName'] + '  ') and -1 != line.find(' -- '):
                    tempString = line.split(' -- ')[1].split(',')[0].strip()
            if tempString:
                i[1]['distributionLongName'] = tempString
            else:
                i[1]['distributionLongName'] = i[1]['distributionName'] # default is class name attribute

            # any additional info
            try:
                n = distro.__doc__.find('Notes\n')
                e = distro.__doc__.find('Examples\n')

                notes =  distro.__doc__[n:e]
                notes = '\n' + notes[notes.find('-\n') + 2:].replace('::', ':').strip()

                i[1]['additionalInfo'] = io.StringIO(notes).readlines()
            except:
                i[1]['additionalInfo'] = ['No additional information available.']

            if distro.name == 'loggamma' and not distro.shapes:
                distro.shapes = 'c'
            if distro.shapes:
                parameterNames = distro.shapes.split(',') + ['location', 'scale']
            else:
                parameterNames = ['location', 'scale']
            i[1]['parameterNames'] = parameterNames

        self.completedWorkItemsList.sort(key=lambda x: x[0])

        pid_trace.pid_trace()


    def WorkItems_CheckOneSecondSessionUpdates(self, countOfWorkItemsRun, totalNumberOfWorkItemsToBeRun):
        self._oneSecondStatusUpdate(
            "Fitted %s of %s Statistical Distributions" % (countOfWorkItemsRun, totalNumberOfWorkItemsToBeRun)
        )


    def SpecificCodeForGeneratingListOfOutputReports(self):
        pid_trace.pid_trace()

        self.functionString = 'PrepareForCharacterizerOutput'
        self.SaveDictionaryOfItemsToSessionStore('status', {'currentStatus':"Generating Report Objects"})
        self.dataObject.fittedStatisticalDistributionsList = self.completedWorkItemsList
        self.ReportsAndGraphsCategoryDict = ReportsAndGraphs.StatisticalDistributionReportsDict(self.dataObject)

        pid_trace.pid_trace()
