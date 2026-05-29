import concurrent.futures.process
import inspect
import io
import logging
import math
import os
import random
import sys
import time

import numpy
import pyeq3
import scipy
import scipy.stats

import settings
import zunzun.forms

from . import ReportsAndGraphs, StatusMonitoredLongRunningProcessPage
from .child_payload import ChildPayload
from .StatusMonitoredLongRunningProcessPage import _ReportsPipelineAborted

_logger = logging.getLogger(__name__)


def parallelWorkFunction(distributionName, data, sortCriteriaName):
    try:
        # _logger.debug('distro: ' + distributionName)
        # tstart = time.time()
        r = pyeq3.Services.SolverService.SolverService().SolveStatisticalDistribution(
            distributionName, data, sortCriteriaName
        )
        # tend = time.time()
        # _logger.debug('elapsed time ' + str(int(tend - tstart)) + ' seconds')
        return r
    except:
        return 0


class StatisticalDistributions(
    StatusMonitoredLongRunningProcessPage.StatusMonitoredLongRunningProcessPage
):
    def __init__(self):
        super().__init__()
        self.parallelWorkItemsList = []

        self.interfaceString = (
            "zunzun/characterize_data_or_statistical_distributions_interface.html"
        )
        self.equationName = None
        self.statisticalDistribution = True
        self.webFormName = "Statistical Distributions"
        self.reniceLevel = 12
        self.characterizerOutputTrueOrReportOutputFalse = True
        self.evaluateAtAPointFormNeeded = False

    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["pdfTitleHTML"] = self.pdfTitleHTML
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.pdfTitleHTML = payload.extra["pdfTitleHTML"]

    def TransferFormDataToDataObject(
        self, request
    ):  # return any error in a user-viewable string (self.dataObject.ErrorString)

        self.pdfTitleHTML = self.webFormName + " " + str(self.dimensionality) + "D"
        self.CommonCreateAndInitializeDataObject(False)
        self.dataObject.equation = self.boundForm.equationBase
        self.dataObject.equation._name = (
            "undefined"  # the EquationBaseClass itself has no equation name
        )
        self.dataObject.textDataEditor = self.boundForm.cleaned_data["textDataEditor"]
        self.dataObject.statisticalDistributionsSortBy = self.boundForm.cleaned_data[
            "statisticalDistributionsSortBy"
        ]
        return ""

    def GenerateListOfWorkItems(self):

        self.update_status(current_status="Sorting Data")

        # required for special beta distribution data max/min case
        self.dataObject.IndependentDataArray[0].sort()

        self.update_status(current_status="Generating List Of Work Items")
        for item in inspect.getmembers(
            scipy.stats
        ):  # weibull max and min are duplicates of Frechet distributions
            if isinstance(item[1], scipy.stats.rv_continuous) and item[0] not in [
                "kstwobign",
                "ncf",
                "levy_stable",
            ]:  # these are very slow, taking too long
                self.parallelWorkItemsList.append(item[0])

    def PerformWorkInParallel(self):

        countOfWorkItemsRun = 0
        totalNumberOfWorkItemsToBeRun = len(self.parallelWorkItemsList)

        # sort order here
        calculateCriteriaForUseInListSorting = "nnlf"
        if "AIC" == self.dataObject.statisticalDistributionsSortBy:
            calculateCriteriaForUseInListSorting = "AIC"
        if "AICc_BA" == self.dataObject.statisticalDistributionsSortBy:
            calculateCriteriaForUseInListSorting = "AICc_BA"

        if self.parallelWorkItemsList:
            data_x = self.dataObject.IndependentDataArray[0]

            def _progress(done: int, _total: int) -> None:
                # Status reflects "tasks the pool has finished" (the `done`
                # arg passed by submit_many), NOT the outer-scope
                # countOfWorkItemsRun which is incremented after yield —
                # the old behavior trailed by one and stalled entirely
                # when many distributions returned falsy. The final
                # post-loop status write outside this loop still reports
                # the precise fittable-distribution count.
                self.WorkItems_CheckOneSecondSessionUpdates(done, totalNumberOfWorkItemsToBeRun)

            try:
                for returnedValue in self.fit_pool.submit_many(
                    parallelWorkFunction,
                    self.parallelWorkItemsList,
                    data_x,
                    calculateCriteriaForUseInListSorting,
                    progress=_progress,
                ):
                    if not returnedValue:
                        # Distribution couldn't be fit (returned 0/None).
                        # Skip — matches legacy `if not returnedValue: continue`.
                        continue
                    countOfWorkItemsRun += 1
                    self.completedWorkItemsList.append(returnedValue)
            except concurrent.futures.process.BrokenProcessPool:
                import logging

                logging.exception("BrokenProcessPool in StatisticalDistributions")
                error_message = (
                    "An internal error occurred during statistical "
                    "distribution fitting. Please try again or contact the administrator."
                )
                self.update_status(
                    redirect_to_results=self._write_terminal_error_html(error_message) or "",
                    process_id=0,
                    completed=True,
                    current_status=error_message,
                    parallel_count=0,
                )
                raise _ReportsPipelineAborted()

        # final save is outside the 'one second updates'. Clearing
        # parallelProcessCount drops the indicator now that no pool is active.
        # Format clarifies the success-vs-total distinction so the count
        # doesn't appear to jump backward from the mid-progress 'X of Y'
        # display (which uses 'tasks the pool finished' for X).
        self.update_status(
            current_status="Fitted %s of %s Statistical Distributions "
            "(remainder could not be fit to the data)"
            % (countOfWorkItemsRun, totalNumberOfWorkItemsToBeRun),
            parallel_count=0,
        )

        for i in self.completedWorkItemsList:
            distro = getattr(
                scipy.stats, i[1]["distributionName"]
            )  # convert distro name back into a distribution object
            # dig out a long name. scipy's names and doc strings
            # are irregular, so dig lfrom the scipy.stats.__doc__ text
            # if present there.
            tempString = None
            lines = io.StringIO(scipy.stats.__doc__).readlines()
            for line in lines:
                if -1 != line.find("  " + i[1]["distributionName"] + "  ") and -1 != line.find(
                    " -- "
                ):
                    tempString = line.split(" -- ")[1].split(",")[0].strip()
            if tempString:
                i[1]["distributionLongName"] = tempString
            else:
                i[1]["distributionLongName"] = i[1][
                    "distributionName"
                ]  # default is class name attribute

            # any additional info
            try:
                n = distro.__doc__.find("Notes\n")
                e = distro.__doc__.find("Examples\n")

                notes = distro.__doc__[n:e]
                notes = "\n" + notes[notes.find("-\n") + 2 :].replace("::", ":").strip()

                i[1]["additionalInfo"] = io.StringIO(notes).readlines()
            except:
                i[1]["additionalInfo"] = ["No additional information available."]

            if distro.name == "loggamma" and not distro.shapes:
                distro.shapes = "c"
            if distro.shapes:
                parameterNames = distro.shapes.split(",") + ["location", "scale"]
            else:
                parameterNames = ["location", "scale"]
            i[1]["parameterNames"] = parameterNames

        self.completedWorkItemsList.sort(key=lambda x: x[0])

    def WorkItems_CheckOneSecondSessionUpdates(
        self, countOfWorkItemsRun, totalNumberOfWorkItemsToBeRun
    ):
        self._oneSecondStatusUpdate(
            "Fitted %s of %s Statistical Distributions"
            % (countOfWorkItemsRun, totalNumberOfWorkItemsToBeRun)
        )

    def SpecificCodeForGeneratingListOfOutputReports(self):

        self.functionString = "PrepareForCharacterizerOutput"
        self.update_status(current_status="Generating Report Objects")
        self.dataObject.fittedStatisticalDistributionsList = self.completedWorkItemsList
        self.ReportsAndGraphsCategoryDict = ReportsAndGraphs.StatisticalDistributionReportsDict(
            self.dataObject
        )
