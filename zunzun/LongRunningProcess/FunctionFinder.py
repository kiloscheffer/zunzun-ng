import concurrent.futures
import concurrent.futures.process
import copy
import inspect
import math
import os
import random
import sys
import time

import numpy
import pyeq3

import settings
import zunzun.formConstants
import zunzun.forms

from ..parallel_pool import FitPool
from . import ReportsAndGraphs, StatusMonitoredLongRunningProcessPage
from .child_payload import ChildPayload
from .StatusMonitoredLongRunningProcessPage import _ReportsPipelineAborted

externalDataCache = pyeq3.dataCache()

# Per-worker dataCache, installed by FitPool's initializer when
# FunctionFinder spawns its sub-pool. The initializer assigns the
# dataCache once at worker startup; parallelWorkFunction reads it
# from this module-level global instead of receiving it via every
# submit() call (which would pickle the cache O(N) times per fit).
_worker_data_cache = None


def _install_worker_data_cache(dataCache):
    """FitPool initializer: install dataCache in worker-global state."""
    global _worker_data_cache
    _worker_data_cache = dataCache


def parallelWorkFunction(inParameterList):
    """Worker-side fit of a single equation against shared data.

    dataCache is read from the module-level ``_worker_data_cache``,
    installed once per worker by FitPool's initializer
    (``_install_worker_data_cache``). This avoids pickling the full
    cache on every submit, which is O(N) IPC overhead for fits with
    many equations and nontrivial input data.
    """
    try:
        j = eval(
            inParameterList[0]
            + "."
            + inParameterList[1]
            + "('"
            + inParameterList[9]
            + "', '"
            + inParameterList[2]
            + "')"
        )
        # _worker_data_cache is installed by _install_worker_data_cache
        # (FitPool initializer) in spawn workers, and by serialWorker in
        # the parent process. If neither has run, fail loudly rather than
        # silently producing a [None, ...] result that climbs fit_exception_count.
        if _worker_data_cache is None:
            raise RuntimeError(
                "parallelWorkFunction called before _worker_data_cache was "
                "installed; pool initializer or serialWorker must run first"
            )
        j.dataCache = _worker_data_cache
        j.polyfunctional2DFlags = inParameterList[3]
        j.polyfunctional3DFlags = inParameterList[4]
        j.xPolynomialOrder = inParameterList[5]
        j.yPolynomialOrder = inParameterList[6]
        j.rationalNumeratorFlags = inParameterList[7]
        j.rationalDenominatorFlags = inParameterList[8]

        if j.ShouldDataBeRejected(j):
            return [None, inParameterList[0], inParameterList[1], inParameterList[2]]

        try:
            j.Solve()
            target = j.CalculateAllDataFittingTarget(j.solvedCoefficients)
        except:
            target = 1.0e300

        if target > 1.0e290:
            return [None, inParameterList[0], inParameterList[1], inParameterList[2]]

        t0 = target  # always make this first for the result list sort function to work properly
        t1 = copy.copy(j.__module__)
        t2 = copy.copy(j.__class__.__name__)
        t3 = copy.copy(j.extendedVersionHandler.__class__.__name__.split("_")[1])
        t4 = copy.copy(j.polyfunctional2DFlags)
        t5 = copy.copy(j.polyfunctional3DFlags)
        t6 = copy.copy(j.xPolynomialOrder)
        t7 = copy.copy(j.yPolynomialOrder)
        t8 = copy.copy(j.rationalNumeratorFlags)
        t9 = copy.copy(j.rationalDenominatorFlags)
        t10 = copy.copy(j.fittingTarget)
        t11 = copy.copy(j.solvedCoefficients)

        j = None

        return [t0, t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11]
    except:
        import logging

        logging.exception("parallelWorkFunction exception")
        return [None, inParameterList[0], inParameterList[1], inParameterList[2]]


def serialWorker(obj, inputList, outputList, dataCache):
    # Install dataCache in parent-process module state via the same
    # initializer the spawn workers use. Single source of truth for the
    # install pattern — parent and spawn workers share the module name
    # but distinct module-state instances, and the assignment only
    # affects whichever process is calling.
    _install_worker_data_cache(dataCache)
    for i in range(len(inputList)):
        try:
            result = parallelWorkFunction(inputList[i])
            if result[0]:
                outputList.append(result)
                obj.countOfSerialWorkItemsRun += 1
            if (obj.countOfSerialWorkItemsRun % 50) == 0:
                obj.WorkItems_CheckOneSecondSessionUpdates()
        except:
            import logging

            logging.exception("serialWorker exception")


class FunctionFinder(StatusMonitoredLongRunningProcessPage.StatusMonitoredLongRunningProcessPage):
    def __init__(self):
        super().__init__()
        self.interfaceString = "zunzun/function_finder_interface.html"
        self.reniceLevel = 19

        self.ff_pool = None  # set in PerformWorkInParallel; cleared in finally

        self.equationName = None
        self.dictionaryOf_BothGoodAndBadCacheData_Flags = {}
        self.numberOfEquationsScannedSoFar = 0
        self.fit_exception_count = 0
        self.fit_skip_count = 0
        self.linearFittingList = []
        self.parallelWorkItemsList = []
        self.parallelFittingResultsByEquationFamilyDictionary = {}
        self.functionFinderResultsList = []
        self.maxFFResultsListSize = 1000  # use ""best"" results  only for database speed and size
        self.bestFFResultTracker = 1.0e300  # to keep track of "best" results

    def build_child_payload(self):
        payload = super().build_child_payload()
        # FunctionFinder-specific config is set by TransferFormDataToDataObject
        # entirely on self.dataObject (extendedEquationTypes, equationFamilyInclusion,
        # fittingTarget, maxCoeffs, maxOrEqual, Max2DPolynomialOrder,
        # Max3DPolynomialOrder).  All of these travel inside payload.data_object.
        # The only field the base class leaves as None that we need is payload.equation,
        # which holds the equationBase (with the populated dataCache) stored at
        # self.dataObject.equation by TransferFormDataToDataObject.
        payload.equation = self.dataObject.equation
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        # Restore the equationBase with its dataCache onto self.dataObject.equation.
        # All other FunctionFinder config fields (extendedEquationTypes,
        # equationFamilyInclusion, fittingTarget, maxCoeffs, maxOrEqual,
        # Max2DPolynomialOrder, Max3DPolynomialOrder) arrive via self.dataObject
        # restored by the base class above.
        self.dataObject.equation = payload.equation

    def TransferFormDataToDataObject(
        self, request
    ):  # return any error in a user-viewable string (self.dataObject.ErrorString)
        self.CommonCreateAndInitializeDataObject(True)
        self.dataObject.equation = self.boundForm.equationBase
        self.dataObject.textDataEditor = self.boundForm.cleaned_data["textDataEditor"]
        self.dataObject.weightedFittingChoice = self.boundForm.cleaned_data["weightedFittingChoice"]
        self.dataObject.extendedEquationTypes = self.boundForm.cleaned_data["extendedEquationTypes"]
        self.dataObject.equationFamilyInclusion = self.boundForm.cleaned_data[
            "equationFamilyInclusion"
        ]
        self.dataObject.fittingTarget = self.boundForm.cleaned_data["fittingTarget"]
        self.dataObject.Max2DPolynomialOrder = (
            len(zunzun.formConstants.polynomialOrder2DChoices) - 1
        )
        self.dataObject.Max3DPolynomialOrder = (
            len(zunzun.formConstants.polynomialOrder3DChoices) - 1
        )
        self.dataObject.maxCoeffs = eval(
            "int(self.boundForm.cleaned_data['smoothnessControl"
            + str(self.dataObject.dimensionality)
            + "D'])"
        )
        self.dataObject.maxOrEqual = self.boundForm.cleaned_data["smoothnessExactOrMax"]
        return ""

    def RenderOutputHTMLToAFileAndSetStatusRedirect(self):

        # The functionfinder + data blob writes below shape what
        # /FunctionFinderResults/ later reads; those stores remain JSON
        # session blobs. The terminal redirect goes to this dispatch's
        # LRPStatus row via update_status — no ownership gate (each
        # dispatch owns its own row).
        self.SaveDictionaryOfItemsToSessionStore(
            "functionfinder",
            {"functionFinderResultsList": self.functionFinderResultsList},
        )

        self.SaveDictionaryOfItemsToSessionStore(
            "data",
            {
                "textDataEditor": self.dataObject.textDataEditor,
                "weightedFittingChoice": self.dataObject.weightedFittingChoice,
                "fittingTarget": self.dataObject.fittingTarget,
                "DependentDataArray": self.dataObject.DependentDataArray,
                "IndependentDataArray": self.dataObject.IndependentDataArray,
            },
        )

        if self.dataObject.dimensionality == 2:
            self.SaveDictionaryOfItemsToSessionStore(
                "data", {"logLinX": self.dataObject.logLinX, "logLinY": self.dataObject.logLinY}
            )

        self.update_status(
            redirect_to_results="/FunctionFinderResults/"
            + str(self.dataObject.dimensionality)
            + "/?RANK=1&unused="
            + str(time.time()),
            completed=True,
        )

    def AddEquationInfoToLinearAndParallelFittingListsAndCheckOneSecond(self):
        global externalDataCache

        self.numberOfEquationsScannedSoFar += 1

        # fit data and only keep non-exception fits
        self.dataObject.equationdataCache = externalDataCache

        # smoothness control
        if self.dataObject.maxOrEqual == "M":  # Max
            if (
                len(self.dataObject.equation.GetCoefficientDesignators())
                > self.dataObject.maxCoeffs
            ):
                self.fit_skip_count += 1
                return
        else:  # Equal
            if (
                len(self.dataObject.equation.GetCoefficientDesignators())
                != self.dataObject.maxCoeffs
            ):
                self.fit_skip_count += 1
                return

        # check for ncoeffs > nobs
        if len(self.dataObject.equation.GetCoefficientDesignators()) > self.dataLength:
            self.fit_skip_count += 1
            return

        # check for functions requiring non-zero nor non-negative data such as 1/x, etc.
        if self.dataObject.equation.ShouldDataBeRejected(self.dataObject.equation):
            self.fit_skip_count += 1
            return

        # see if the cache generation yielded any overly large numbers or exceptions
        try:
            self.dataObject.equation.dataCache.FindOrCreateAllDataCache(self.dataObject.equation)
        except:
            self.fit_skip_count += 1
            return
        for i in self.dataObject.equation.GetDataCacheFunctions():
            try:
                if (
                    i[0] in self.dictionaryOf_BothGoodAndBadCacheData_Flags
                ) != 1:  # if not in the cached flags, add it
                    if (
                        max(self.dataObject.equation.dataCache.allDataCacheDictionary[i[0]])
                        >= 1.0e300
                    ):
                        self.dictionaryOf_BothGoodAndBadCacheData_Flags[i[0]] = False  # (bad)
                    else:
                        self.dictionaryOf_BothGoodAndBadCacheData_Flags[i[0]] = True  # (good)
            except:
                import logging

                logging.exception("oodbadcachedata flags exception, i = " + str(i))
            if self.dictionaryOf_BothGoodAndBadCacheData_Flags[i[0]] == False:  # if bad
                self.fit_skip_count += 1
                return

        t0 = copy.copy(self.dataObject.equation.__module__)
        t1 = copy.copy(self.dataObject.equation.__class__.__name__)
        t2 = copy.copy(
            self.dataObject.equation.extendedVersionHandler.__class__.__name__.split("_")[1]
        )
        t3 = copy.copy(self.dataObject.equation.polyfunctional2DFlags)
        t4 = copy.copy(self.dataObject.equation.polyfunctional3DFlags)
        t5 = copy.copy(self.dataObject.equation.xPolynomialOrder)
        t6 = copy.copy(self.dataObject.equation.yPolynomialOrder)
        t7 = copy.copy(self.dataObject.equation.rationalNumeratorFlags)
        t8 = copy.copy(self.dataObject.equation.rationalDenominatorFlags)
        t9 = copy.copy(self.dataObject.equation.fittingTarget)

        if (
            self.dataObject.equation.CanLinearSolverBeUsedForSSQABS()
            and self.dataObject.equation.fittingTarget == "SSQABS"
        ):
            self.linearFittingList.append([t0, t1, t2, t3, t4, t5, t6, t7, t8, t9])
        else:
            self.parallelWorkItemsList.append([t0, t1, t2, t3, t4, t5, t6, t7, t8, t9])
            if t0 not in list(self.parallelFittingResultsByEquationFamilyDictionary.keys()):
                self.parallelFittingResultsByEquationFamilyDictionary[t0] = [0, 0]
            self.parallelFittingResultsByEquationFamilyDictionary[t0][0] += 1
        self.WorkItems_CheckOneSecondSessionUpdates_Scanning()

    def GenerateListOfWorkItems(self):
        global externalDataCache

        externalDataCache = self.dataObject.equation.dataCache

        self.dataLength = len(externalDataCache.allDataCacheDictionary["DependentData"])

        # loop through all equations
        if self.dataObject.dimensionality == 2:
            loopover = inspect.getmembers(pyeq3.Models_2D)
        else:
            loopover = inspect.getmembers(pyeq3.Models_3D)
        for submodule in loopover:
            if inspect.ismodule(submodule[1]):
                if submodule[0] not in self.dataObject.equationFamilyInclusion:
                    continue
                for equationClass in inspect.getmembers(submodule[1]):
                    if inspect.isclass(equationClass[1]):
                        for (
                            extendedName
                        ) in pyeq3.ExtendedVersionHandlers.extendedVersionHandlerNameList:
                            if "STANDARD" not in self.dataObject.extendedEquationTypes:
                                if extendedName in [
                                    "",
                                    "Default",
                                    "Offset",
                                    "PlusLine",
                                    "PlusPlane",
                                ]:
                                    continue
                            if "RECIPROCAL" not in self.dataObject.extendedEquationTypes:
                                if -1 != extendedName.find("Reciprocal"):
                                    continue
                            if "INVERSE" not in self.dataObject.extendedEquationTypes:
                                if -1 != extendedName.find("Inverse"):
                                    continue
                            if "LINEAR_GROWTH" not in self.dataObject.extendedEquationTypes:
                                if -1 != extendedName.find("LinearGrowth"):
                                    continue
                            if "LINEAR_DECAY" not in self.dataObject.extendedEquationTypes:
                                if -1 != extendedName.find("LinearDecay"):
                                    continue
                            if "EXPONENTIAL_GROWTH" not in self.dataObject.extendedEquationTypes:
                                if -1 != extendedName.find("ExponentialGrowth"):
                                    continue
                            if "EXPONENTIAL_DECAY" not in self.dataObject.extendedEquationTypes:
                                if -1 != extendedName.find("ExponentialDecay"):
                                    continue

                            if (-1 != extendedName.find("Offset")) and (
                                equationClass[1].autoGenerateOffsetForm == False
                            ):
                                continue
                            if (-1 != extendedName.find("PlusLine")) and (
                                equationClass[1].autoGeneratePlusLineForm == False
                            ):
                                continue
                            if (-1 != extendedName.find("PlusPlane")) and (
                                equationClass[1].autoGeneratePlusPlaneForm == False
                            ):
                                continue
                            if (-1 != extendedName.find("Reciprocal")) and (
                                equationClass[1].autoGenerateReciprocalForm == False
                            ):
                                continue
                            if (-1 != extendedName.find("Inverse")) and (
                                equationClass[1].autoGenerateInverseForms == False
                            ):
                                continue
                            if (-1 != extendedName.find("Growth")) and (
                                equationClass[1].autoGenerateGrowthAndDecayForms == False
                            ):
                                continue
                            if (-1 != extendedName.find("Decay")) and (
                                equationClass[1].autoGenerateGrowthAndDecayForms == False
                            ):
                                continue

                            try:
                                j = equationClass[1](self.dataObject.fittingTarget, extendedName)
                            except:
                                continue

                            self.dataObject.equation = j
                            self.dataObject.equation.FamilyName = submodule[0]

                            self.dataObject.equation.dataCache = externalDataCache

                            if (
                                self.dataObject.equation.userSelectablePolynomialFlag == False
                                and self.dataObject.equation.userCustomizablePolynomialFlag == False
                                and self.dataObject.equation.userSelectablePolyfunctionalFlag
                                == False
                                and self.dataObject.equation.userSelectableRationalFlag == False
                            ):
                                self.AddEquationInfoToLinearAndParallelFittingListsAndCheckOneSecond()

                            if self.dataObject.equation.userSelectablePolynomialFlag == True:
                                if self.dataObject.equation.GetDimensionality() == 2:
                                    for k in range(self.dataObject.Max2DPolynomialOrder + 1):
                                        self.dataObject.equation.xPolynomialOrder = k
                                        self.AddEquationInfoToLinearAndParallelFittingListsAndCheckOneSecond()
                                else:
                                    for k in range(self.dataObject.Max3DPolynomialOrder + 1):
                                        for l in range(self.dataObject.Max3DPolynomialOrder + 1):  # noqa: E741
                                            self.dataObject.equation.xPolynomialOrder = k
                                            self.dataObject.equation.yPolynomialOrder = l
                                            self.AddEquationInfoToLinearAndParallelFittingListsAndCheckOneSecond()

                            # polyfunctionals are not used unless unweighted SSQ due to CPU hogging
                            if (
                                self.dataObject.equation.userSelectablePolyfunctionalFlag == True
                                and self.dataObject.fittingTarget == "SSQABS"
                                and len(
                                    self.dataObject.equation.dataCache.allDataCacheDictionary[
                                        "Weights"
                                    ]
                                )
                                == 0
                            ):
                                functionList = []
                                if self.dataObject.equation.GetDimensionality() == 2:
                                    for i in range(
                                        len(self.dataObject.equation.polyfunctionalEquationList)
                                    ):
                                        functionList.append(i)

                                    loopMaxCoeffs = 4
                                    for coeffNumber in range(1, loopMaxCoeffs + 1):
                                        xcombolist = self.UniqueCombinations(
                                            functionList, coeffNumber
                                        )
                                        for k in xcombolist:
                                            self.dataObject.equation.__init__(
                                                self.dataObject.fittingTarget, extendedName
                                            )
                                            self.dataObject.equation.dataCache = externalDataCache
                                            self.dataObject.equation.polyfunctional2DFlags = k
                                            self.AddEquationInfoToLinearAndParallelFittingListsAndCheckOneSecond()
                                            if (
                                                len(self.dataObject.equation.polyfunctional2DFlags)
                                                <= loopMaxCoeffs
                                                and 0
                                                not in self.dataObject.equation.polyfunctional2DFlags
                                                and len(
                                                    self.dataObject.equation.polyfunctional2DFlags
                                                )
                                                < self.dataObject.maxCoeffs
                                            ):
                                                self.dataObject.equation.__init__(
                                                    self.dataObject.fittingTarget, extendedName
                                                )
                                                self.dataObject.equation.dataCache = (
                                                    externalDataCache
                                                )
                                                temp = copy.copy(
                                                    self.dataObject.equation.polyfunctional2DFlags
                                                )
                                                temp.append(
                                                    0
                                                )  # offset term if one is not already used and enough coefficients
                                                self.dataObject.equation.polyfunctional2DFlags = (
                                                    temp
                                                )
                                                self.AddEquationInfoToLinearAndParallelFittingListsAndCheckOneSecond()

                                else:
                                    for k in range(
                                        len(self.dataObject.equation.polyfunctionalEquationList_X)
                                    ):
                                        for l in range(  # noqa: E741
                                            len(
                                                self.dataObject.equation.polyfunctionalEquationList_Y
                                            )
                                        ):
                                            if [l, k] not in functionList:
                                                functionList.append([k, l])

                                    loopMaxCoeffs = 2
                                    xcombolist = self.UniqueCombinations(
                                        functionList, loopMaxCoeffs
                                    )
                                    for k in xcombolist:
                                        self.dataObject.equation.__init__(
                                            self.dataObject.fittingTarget, extendedName
                                        )
                                        self.dataObject.equation.dataCache = externalDataCache
                                        self.dataObject.equation.polyfunctional3DFlags = k
                                        self.AddEquationInfoToLinearAndParallelFittingListsAndCheckOneSecond()
                                        if (
                                            len(self.dataObject.equation.polyfunctional3DFlags)
                                            == loopMaxCoeffs
                                            and [0, 0]
                                            not in self.dataObject.equation.polyfunctional3DFlags
                                            and len(self.dataObject.equation.polyfunctional3DFlags)
                                            < self.dataObject.maxCoeffs
                                        ):
                                            self.dataObject.equation.__init__(
                                                self.dataObject.fittingTarget, extendedName
                                            )
                                            self.dataObject.equation.dataCache = externalDataCache
                                            temp = copy.copy(
                                                self.dataObject.equation.polyfunctional3DFlags
                                            )
                                            temp.append(
                                                [0, 0]
                                            )  # offset term if one is not already used
                                            self.dataObject.equation.polyfunctional3DFlags = temp
                                            self.AddEquationInfoToLinearAndParallelFittingListsAndCheckOneSecond()

                            # polyrationals are combinations of individual functions with some maximum number of combinations
                            if self.dataObject.equation.userSelectableRationalFlag == 1:
                                maxCoeffs = 2  # arbitrary choice of maximum number of numerator or denominator functions in a polyrational for this example
                                functionList = []  # make a list of function indices
                                for i in range(len(self.dataObject.equation.rationalEquationList)):
                                    functionList.append(i)

                                for numeratorCoeffCount in range(1, maxCoeffs + 1):
                                    numeratorComboList = self.UniqueCombinations(
                                        functionList, numeratorCoeffCount
                                    )
                                    for numeratorCombo in numeratorComboList:
                                        for denominatorCoeffCount in range(1, maxCoeffs + 1):
                                            denominatorComboList = self.UniqueCombinations2(
                                                functionList, denominatorCoeffCount
                                            )
                                            for denominatorCombo in denominatorComboList:
                                                self.dataObject.equation.__init__(
                                                    self.dataObject.fittingTarget, extendedName
                                                )
                                                self.dataObject.equation.dataCache = (
                                                    externalDataCache
                                                )
                                                self.dataObject.equation.rationalNumeratorFlags = (
                                                    numeratorCombo
                                                )
                                                self.dataObject.equation.rationalDenominatorFlags = denominatorCombo
                                                self.AddEquationInfoToLinearAndParallelFittingListsAndCheckOneSecond()

        self.update_status(
            current_status="Scanned %s Equations : %s OK, %s skipped, %s exceptions"
            % (
                self.numberOfEquationsScannedSoFar,
                len(self.linearFittingList) + len(self.parallelWorkItemsList),
                self.fit_skip_count,
                self.fit_exception_count,
            )
        )

    def PerformWorkInParallel(self):

        self.update_status(current_status="Preparing to fit equations, one minute please...")
        self.countOfParallelWorkItemsRun = 0
        self.countOfSerialWorkItemsRun = 0
        self.totalNumberOfParallelWorkItemsToBeRun = len(self.parallelWorkItemsList)
        self.totalNumberOfSerialWorkItemsToBeRun = len(self.linearFittingList)

        dataCache = self.dataObject.equation.dataCache

        if self.parallelWorkItemsList:
            # FunctionFinder uses its OWN FitPool (not the shared
            # self.fit_pool) so the dataCache can be installed in
            # worker-global state via the initializer, avoiding O(N)
            # per-task pickling. The reports/distributions phases keep
            # using self.fit_pool. Worker startup cost (~1-2s for one
            # extra round of spawn imports) is more than recovered by
            # eliminating per-equation cache serialization.
            self.ff_pool = FitPool(
                initializer=_install_worker_data_cache,
                initargs=(dataCache,),
            )
            ff_pool_error = False
            try:
                # `futures` is a set, not a dict — the parallelWorkItem
                # tuple itself is never read after submit (the drain loop
                # only consumes fut.result()), so retaining N item refs in
                # a dict value was O(N) wasted memory.
                futures = {
                    self.ff_pool.submit(parallelWorkFunction, item)
                    for item in self.parallelWorkItemsList
                }

                while futures:
                    try:
                        done, _ = concurrent.futures.wait(
                            futures,
                            timeout=1.0,
                            return_when=concurrent.futures.FIRST_COMPLETED,
                        )
                    except concurrent.futures.process.BrokenProcessPool:
                        ff_pool_error = True
                        import logging

                        logging.exception(
                            "BrokenProcessPool in FunctionFinder.PerformWorkInParallel"
                        )
                        error_message = (
                            "An internal error occurred during equation "
                            "fitting. Please try again or contact the administrator."
                        )
                        self.update_status(
                            redirect_to_results=self._write_terminal_error_html(error_message)
                            or "",
                            process_id=0,
                            completed=True,
                            current_status=error_message,
                            parallel_count=0,
                        )
                        raise _ReportsPipelineAborted()

                    for fut in done:
                        try:
                            resultValue = fut.result()
                        except concurrent.futures.process.BrokenProcessPool:
                            ff_pool_error = True
                            import logging

                            logging.exception(
                                "BrokenProcessPool surfaced via .result() in FunctionFinder"
                            )
                            error_message = (
                                "An internal error occurred during equation "
                                "fitting. Please try again or contact the administrator."
                            )
                            self.update_status(
                                redirect_to_results=self._write_terminal_error_html(error_message)
                                or "",
                                process_id=0,
                                completed=True,
                                current_status=error_message,
                                parallel_count=0,
                            )
                            raise _ReportsPipelineAborted()
                        except concurrent.futures.CancelledError:
                            # Pool was shut down via cancel_futures=True
                            # (CheckIfStillUsed abandoned-fit detection now
                            # cancels self.ff_pool explicitly — see
                            # CheckIfStillUsed). Raise _ReportsPipelineAborted
                            # (not return) so base PerformAllWork skips
                            # RenderOutputHTML and doesn't write a redirect
                            # to an empty results page.
                            raise _ReportsPipelineAborted()
                        except Exception:
                            self.fit_exception_count += 1
                            futures.discard(fut)
                            continue

                        if resultValue[0]:
                            if len(self.functionFinderResultsList) < self.maxFFResultsListSize:
                                self.functionFinderResultsList.append(resultValue)
                            else:
                                self.functionFinderResultsList.sort()
                                if self.functionFinderResultsList[-1][0] < self.bestFFResultTracker:
                                    self.bestFFResultTracker = self.functionFinderResultsList[-1][0]
                                    self.functionFinderResultsList[-1] = resultValue
                            self.countOfParallelWorkItemsRun += 1
                        self.parallelFittingResultsByEquationFamilyDictionary[resultValue[1]][
                            1
                        ] += 1
                        futures.discard(fut)

                    self.WorkItems_CheckOneSecondSessionUpdates()
            finally:
                if self.ff_pool is not None:
                    # On error, cancel pending and don't wait for in-flight
                    # workers (they may be running multi-minute pyeq3 fits
                    # the user will never see the result of). On success,
                    # wait=True for clean teardown.
                    if ff_pool_error:
                        self.ff_pool.shutdown(wait=False, cancel_futures=True)
                    else:
                        self.ff_pool.shutdown(wait=True)
                    self.ff_pool = None
                # Reset the parent-process module global so the dataCache
                # ref is releasable through the rest of PerformAllWork
                # (PDF gen, HTML render, redirect). serialWorker (if it
                # runs again later) reinstalls it.
                global _worker_data_cache
                _worker_data_cache = None

        # Linear fits are very fast — run these in the existing process which
        # saves on interprocess communication overhead.
        if self.totalNumberOfSerialWorkItemsToBeRun:
            serialWorker(
                self,
                self.linearFittingList,
                self.functionFinderResultsList,
                self.dataObject.equation.dataCache,
            )

        self.WorkItems_CheckOneSecondSessionUpdates()
        # All parallel workers have drained; clear the indicator so the status
        # page stops showing the count during post-processing phases.
        self.update_status(
            current_status="%s Total Equations Fitted, combining lists..."
            % (self.countOfParallelWorkItemsRun + self.countOfSerialWorkItemsRun),
            parallel_count=0,
        )

        # final status update is outside the 'one second updates'
        self.update_status(
            current_status="%s Total Equations Fitted, sorting..."
            % (self.countOfParallelWorkItemsRun + self.countOfSerialWorkItemsRun)
        )

        self.functionFinderResultsList.sort()  # uses the default sort on list element zero

        # The legacy code cleared processID here to bypass CheckIfStillUsed
        # during the chunked-pool report phase. With the FitPool refactor,
        # CheckIfStillUsed correctly compares the row's process_id against
        # os.getpid() (no teardown when they match), and the base
        # PerformAllWork's end-of-success cleanup clears process_id AFTER
        # RenderOutputHTMLToAFileAndSetStatusRedirect. Clearing here would
        # prematurely allow a second concurrent fit to be accepted during
        # the (small but real) post-PerformWorkInParallel window.

    def WorkItems_CheckOneSecondSessionUpdates(self):
        sortedFamilyNameList = sorted(self.parallelFittingResultsByEquationFamilyDictionary.keys())
        if not sortedFamilyNameList:
            # All-linear run (no families registered for parallel fitting).
            # Still call the helper so CheckIfStillUsed fires and the
            # serial-progress counter is visible to the user.
            self._oneSecondStatusUpdate(
                "%s of %s Equations Fitted Linearly"
                % (
                    self.countOfSerialWorkItemsRun,
                    self.totalNumberOfSerialWorkItemsToBeRun,
                )
            )
            return

        familyString = "<table>"
        for familyName in sortedFamilyNameList:
            total = self.parallelFittingResultsByEquationFamilyDictionary[familyName][0]
            soFar = self.parallelFittingResultsByEquationFamilyDictionary[familyName][1]
            if soFar > 0 and total != soFar:  # bold the family currently fitting
                familyString += (
                    '<tr><td><b>%s</b></td><td><b>of</b></td><td><b>%s</b></td><td align="center">%s</td><td>Equations Fitted Non-Linearly</td></tr>'
                    % (soFar, total, familyName.split(".")[-1])
                )
            elif total == soFar:
                familyString += (
                    '<tr><td>%s</td><td>of</td><td>%s</td><td align="center"><b><font color="green">%s</font></b></td><td>Equations Fitted Non-Linearly</td></tr>'
                    % (soFar, total, familyName.split(".")[-1])
                )
            else:
                familyString += (
                    '<tr><td>%s</td><td>of</td><td>%s</td><td align="center">%s</td><td>Equations Fitted Non-Linearly</td></tr>'
                    % (soFar, total, familyName.split(".")[-1])
                )
        familyString += "</table><br>"

        if self.countOfSerialWorkItemsRun == 0:
            summary = (
                familyString
                + "<b>%s of %s</b> Equations Fitted Non-Linearly<br>%s of %s Equations Fitted Linearly"
                % (
                    self.countOfParallelWorkItemsRun,
                    self.totalNumberOfParallelWorkItemsToBeRun,
                    self.countOfSerialWorkItemsRun,
                    self.totalNumberOfSerialWorkItemsToBeRun,
                )
            )
        else:
            summary = (
                familyString
                + "%s of %s Equations Fitted Non-Linearly<br><b>%s of %s</b> Equations Fitted Linearly"
                % (
                    self.countOfParallelWorkItemsRun,
                    self.totalNumberOfParallelWorkItemsToBeRun,
                    self.countOfSerialWorkItemsRun,
                    self.totalNumberOfSerialWorkItemsToBeRun,
                )
            )

        self._oneSecondStatusUpdate(summary)

    def WorkItems_CheckOneSecondSessionUpdates_Scanning(self):
        self._oneSecondStatusUpdate(
            "Scanned %s Equations : %s OK, %s skipped, %s exceptions"
            % (
                self.numberOfEquationsScannedSoFar,
                len(self.linearFittingList) + len(self.parallelWorkItemsList),
                self.fit_skip_count,
                self.fit_exception_count,
            )
        )

    def CreateUnboundInterfaceForm(self, request):
        dictionaryToReturn = {}
        dictionaryToReturn["dimensionality"] = str(self.dimensionality)

        dictionaryToReturn["header_text"] = "ZunZunNG"
        dictionaryToReturn["subtitle_text"] = (
            str(self.dimensionality) + "D Function Finder Interface"
        )
        dictionaryToReturn["title_string"] = (
            "ZunZunNG " + str(self.dimensionality) + "D Function Finder Interface"
        )

        # make a dimensionality-based unbound Django form
        if self.dimensionality == 2:
            self.unboundForm = zunzun.forms.FunctionFinder_2D()
            self.unboundForm.fields["textDataEditor"].initial += (
                self.extraExampleDataTextForWeightedFitting + self.defaultData2D
            )
        else:
            self.unboundForm = zunzun.forms.FunctionFinder_3D()
            self.unboundForm.fields["textDataEditor"].initial += (
                self.extraExampleDataTextForWeightedFitting + self.defaultData3D
            )

        # set the form to have either default or session text data
        temp = self.LoadItemFromSessionStore(
            "data", "textDataEditor_" + str(self.dimensionality) + "D"
        )
        if temp:
            self.unboundForm.fields["textDataEditor"].initial = temp
        temp = self.LoadItemFromSessionStore("data", "commaConversion")
        if temp:
            self.unboundForm.fields["commaConversion"].initial = temp
        temp = self.LoadItemFromSessionStore("data", "weightedFittingChoice")
        if temp:
            self.unboundForm.fields["weightedFittingChoice"].initial = temp

        self.unboundForm.weightedFittingPossibleFlag = 1
        dictionaryToReturn["mainForm"] = self.unboundForm

        return dictionaryToReturn

    def CreateBoundInterfaceForm(self, request):
        # make a dimensionality-based bound Django form
        self.boundForm = eval(
            "zunzun.forms.FunctionFinder_" + str(self.dimensionality) + "D(request.POST)"
        )
        self.boundForm.dimensionality = str(self.dimensionality)

    def UniqueCombinations(self, items, n):
        if n == 0:
            yield []
        else:
            for i in range(len(items)):
                for cc in self.UniqueCombinations(items[i + 1 :], n - 1):
                    yield [items[i]] + cc

    def UniqueCombinations2(self, items2, n2):
        if n2 == 0:
            yield []
        else:
            for i2 in range(len(items2)):
                for cc2 in self.UniqueCombinations2(items2[i2 + 1 :], n2 - 1):
                    yield [items2[i2]] + cc2

    def Combinations(self, items, n):
        if n == 0:
            yield []
        else:
            for i in range(len(items)):
                for cc in self.UniqueCombinations(items[i + 1 :], n - 1):
                    yield [items[i]] + cc

    def CreateOutputReportsInParallelUsingProcessPool(self):
        pass  # function finder *results* page makes these

    def GenerateListOfOutputReports(self):
        pass  # function finder *results* page makes these

    def CreateReportPDF(self):
        pass  # no PDF file
