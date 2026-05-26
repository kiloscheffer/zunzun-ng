from django.shortcuts import render
import django.http  # to raise 404's
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.cache import cache_page
from django.contrib.sessions.backends.db import SessionStore
from django import db
from django.db import close_old_connections
from django.core.mail import EmailMessage

import settings

import os, time, urllib.parse
from . import forms
import numpy, multiprocessing
import scipy.interpolate

import pyeq3
from . import LongRunningProcess
from . import platform_compat
from .LongRunningProcess.child_payload import _run_fit_child

from django_ratelimit.decorators import ratelimit


def _housekeeping_child(temp_dir: str, max_size_mb: int) -> None:
    """Top-level entrypoint for the HomePageView housekeeping fork.

    Must be module-level (not nested) for spawn to pickle it.
    Clears expired sessions and trims temp/ when it exceeds
    max_size_mb.
    """
    from django.contrib.sessions.backends.db import SessionStore as _SessionStore

    try:
        _SessionStore().clear_expired()

        totalDirSize = 0
        dirInfo = []
        for item in os.listdir(temp_dir):
            itempath = os.path.join(temp_dir, item)
            if os.path.isfile(itempath):
                fileSize = os.path.getsize(itempath)
                fileMtime = os.path.getmtime(itempath)
                dirInfo.append([fileMtime, fileSize, item])
                totalDirSize += fileSize

        maxSize = max_size_mb * 1000000

        if totalDirSize > maxSize:
            totalReduction = 0
            reductionAmount = (totalDirSize - maxSize) + (maxSize * 0.25)
            dirInfo.sort()
            for fileItem in dirInfo:
                if totalReduction < reductionAmount:
                    totalReduction += fileItem[1]
                    try:
                        os.remove(os.path.join(temp_dir, fileItem[2]))
                    except Exception:
                        pass
                else:
                    break
    except Exception:
        pass


@cache_control(no_cache=True)
@ratelimit(key="ip", rate="12/m", block=False)
def EvaluateAtAPointView(request):
    import os, sys, time

    if CommonToAllViews(
        request
    ):  # any referrer blocks or web request checks processed here
        raise django.http.Http404

    # only allow POST for this view
    if request.method != "POST":
        return HttpResponse("I am not able to process your request.")

    # used to read data from session
    if "session_key_data" not in list(request.session.keys()):
        return HttpResponse(
            "I was unable to read required session data, my apologies. Are session cookies turned off in your browser?"
        )

    LRP = LongRunningProcess.FittingBaseClass.FittingBaseClass()
    LRP.session_key_data = request.session["session_key_data"]

    # instantiate an equation object using session equation family and name
    LRP.dimensionality = LRP.LoadItemFromSessionStore("data", "dimensionality")
    inEquationName = LRP.LoadItemFromSessionStore("data", "equationName")
    inEquationFamilyName = LRP.LoadItemFromSessionStore("data", "equationFamilyName")
    equation = LRP.GetEquationFromNameAndFamily(
        inEquationName,
        inEquationFamilyName,
        checkForSplinesAndUserDefinedFunctionsFlag=1,
    )
    if not equation:  # could not find a matching equation
        return HttpResponse(
            'Could not find the equation "'
            + str(inEquationName)
            + '" in the equation family "'
            + str(inEquationFamilyName)
            + '".'
        )

    # read equation-specific information from session data and assign to equation object
    if equation.splineFlag:
        # scipySpline (the live scipy spline object) isn't saved — see
        # FitSpline.SaveSpecificDataToSessionStore. solvedCoefficients IS
        # the tck tuple, which we reconstruct into a callable spline.
        # pyeq3/Models_2D/Spline.CalculateModelPredictions calls
        # self.scipySpline(X); BSpline is callable with matching
        # semantics. For 3D, wrap bisplev in an .ev(X, Y) helper to
        # match Models_3D/Spline's self.scipySpline.ev(X, Y) call shape.
        tck = LRP.LoadItemFromSessionStore("data", "solvedCoefficients")
        if LRP.dimensionality == 2:
            equation.scipySpline = scipy.interpolate.BSpline(
                numpy.array(tck[0]), numpy.array(tck[1]), int(tck[2])
            )
        else:
            tx = numpy.array(tck[0])
            ty = numpy.array(tck[1])
            c = numpy.array(tck[2])
            kx = int(tck[3])
            ky = int(tck[4])

            class _BivariateSplineFromTck:
                def ev(self, X, Y):
                    return scipy.interpolate.bisplev(X, Y, (tx, ty, c, kx, ky))

            equation.scipySpline = _BivariateSplineFromTck()
    elif equation.userDefinedFunctionFlag:
        equation.userDefinedFunctionText = LRP.LoadItemFromSessionStore(
            "data", "udfEditor_" + str(equation.GetDimensionality()) + "D"
        )
        equation.ParseAndCompileUserFunctionString(
            equation.userDefinedFunctionText, LRP.dimensionality
        )
    elif equation.userSelectablePolynomialFlag:
        equation.xPolynomialOrder = LRP.LoadItemFromSessionStore(
            "data", "xPolynomialOrder"
        )
        equation.yPolynomialOrder = LRP.LoadItemFromSessionStore(
            "data", "yPolynomialOrder"
        )
    elif equation.userSelectableRationalFlag:
        equation.rationalNumeratorFlags = LRP.LoadItemFromSessionStore(
            "data", "rationalNumeratorFlags"
        )
        equation.rationalDenominatorFlags = LRP.LoadItemFromSessionStore(
            "data", "rationalDenominatorFlags"
        )
    elif equation.userSelectablePolyfunctionalFlag:
        equation.polyfunctional2DFlags = LRP.LoadItemFromSessionStore(
            "data", "polyfunctional2DFlags"
        )
        equation.polyfunctional3DFlags = LRP.LoadItemFromSessionStore(
            "data", "polyfunctional3DFlags"
        )
    elif equation.userCustomizablePolynomialFlag:
        equation.polynomial2DFlags = LRP.LoadItemFromSessionStore(
            "data", "polynomial2DFlags"
        )
    else:
        equation.fittingTarget = LRP.LoadItemFromSessionStore("data", "fittingTarget")

    # solvedCoefficients is stored as a list after _json_native. pyeq3's
    # CalculateModelPredictions expects an ndarray for regular equations.
    # For splines, solvedCoefficients IS the tck tuple (already consumed
    # above to reconstruct equation.scipySpline) and pyeq3's Spline
    # CalculateModelPredictions ignores inCoeffs, so leave it as-is.
    raw_coeffs = LRP.LoadItemFromSessionStore("data", "solvedCoefficients")
    if equation.splineFlag:
        equation.solvedCoefficients = raw_coeffs
    else:
        equation.solvedCoefficients = numpy.array(raw_coeffs)

    # make bound Django form and call form.is_valid()
    try:
        evaluationForm = eval(
            "forms.EvaluateAtAPointForm_" + str(LRP.dimensionality) + "D(request.POST)"
        )
    except:
        time.sleep(1.0)
        evaluationForm = eval(
            "forms.EvaluateAtAPointForm_" + str(LRP.dimensionality) + "D(request.POST)"
        )

    if not evaluationForm.is_valid():
        return HttpResponse("Invalid data submitted, please try again.")

    # load data to be evaluated from the cleaned form data
    if LRP.dimensionality == 2:
        equation.dataCache.allDataCacheDictionary["IndependentData"] = numpy.array(
            [[evaluationForm.cleaned_data["x"]], [1.0]]
        )
    else:
        equation.dataCache.allDataCacheDictionary["IndependentData"] = numpy.array(
            [[evaluationForm.cleaned_data["x"]], [evaluationForm.cleaned_data["y"]]]
        )
    equation.dataCache.FindOrCreateAllDataCache(equation)

    # evaluate data, checking bounds of result
    try:
        pointValue = equation.CalculateModelPredictions(
            equation.solvedCoefficients, equation.dataCache.allDataCacheDictionary
        )
        try:
            pointValue = pointValue[
                0
            ]  # spline evaluation was returning scalar and not array
        except:
            pass
        if pointValue < 1.0e300 and pointValue > -1.0e300:
            pointValueAsString = "evaluates to <b>" + str(pointValue) + "</b>"
        else:
            pointValueAsString = "Evaluation was outside numeric bounds of +/- 1.0E300, please check the data."
    except:
        exceptionString = str(sys.exc_info()[0]) + "  " + str(sys.exc_info()[1]) + "\n"
        exceptionString += inEquationFamilyName + "\n"
        exceptionString += inEquationName + "\n"
        exceptionString += str(equation.solvedCoefficients) + "\n"
        exceptionString += str(
            equation.dataCache.allDataCacheDictionary["IndependentData"]
        )
        pointValueAsString = (
            "Exception in evaluation, please check the data. Exception text: "
            + exceptionString
        )
        if settings.EXCEPTION_EMAIL_ADDRESS:
            EmailMessage(
                "Site exception in evaluation at a point",
                exceptionString,
                to=[settings.EXCEPTION_EMAIL_ADDRESS],
            ).send()
    return HttpResponse(pointValueAsString)


def ConvertSecondsToHMS(seconds):
    hours = int(seconds / 3600.0)
    seconds -= 3600 * hours
    minutes = int(seconds / 60.0)
    seconds -= int(60 * minutes)
    return "%02d:%02d:%02d" % (hours, minutes, seconds)


@cache_control(no_cache=True)
def StatusView(request):
    try:
        session_status = SessionStore(request.session["session_key_status"])
    except:
        return HttpResponse("I could not read your session data, please try again.")

    # Completion handoff: read, clear, serve file body OR HttpResponseRedirect.
    # Behavior unchanged from the original implementation.
    if "redirectToResultsFileOrURL" in session_status:
        if session_status["redirectToResultsFileOrURL"] != "":
            redirect = session_status["redirectToResultsFileOrURL"]
            session_status["redirectToResultsFileOrURL"] = ""

            s = session_status
            save_complete = False
            saveRetries = 0
            while not save_complete:
                try:
                    s.save()
                    save_complete = True
                except Exception as e:
                    time.sleep(0.1)
                    saveRetries += 1
                    if saveRetries > 100:
                        raise e

            db.connections.close_all()
            close_old_connections()

            if redirect.startswith(settings.TEMP_FILES_DIR):
                s = open(redirect, "r").read()
                return HttpResponse(s)
            else:
                return HttpResponseRedirect(redirect)

    # In-progress branch: render the template. Heartbeat write moved to
    # StatusUpdateView so there is a single owner of that side effect.
    try:
        currentStatus = session_status["currentStatus"]
        startTime = session_status["start_time"]
    except:
        return HttpResponse(
            "I could not read your session data, my apologies. This is usually caused by a stale browser cookie. Please delete the ZunZunNG browser cookie and try again."
        )

    loadavg = platform_compat.get_loadavg()
    return render(request, "zunzun/status.html", {
        "title_string": "ZunZunNG - Working on your fit",
        "header_text": "ZunZunNG",
        "currentStatus": currentStatus,
        "elapsed": ConvertSecondsToHMS(time.time() - startTime),
        "loadavg": list(loadavg),
        "coreCount": multiprocessing.cpu_count(),
    })


@cache_control(no_cache=True)
def StatusUpdateView(request):
    """JSON polling endpoint for the status page.

    Returns the live status fields (currentStatus, elapsed, loadavg) as JSON.
    On completion, returns {"completed": True} and intentionally does NOT
    clear redirectToResultsFileOrURL — that's StatusView's job when the
    browser follows up.
    """
    try:
        session_status = SessionStore(request.session["session_key_status"])
    except Exception:
        # Matches StatusView's defensive bare-except on the same call:
        # missing request-session key, malformed key, transient DB issue.
        # JS treats any non-2xx as "wait and retry" so this is graceful.
        return JsonResponse({"error": "no_session"}, status=400)

    # Completion: report and return immediately. Do NOT clear the key.
    if session_status.get("redirectToResultsFileOrURL", ""):
        return JsonResponse({"completed": True})

    try:
        currentStatus = session_status["currentStatus"]
        startTime = session_status["start_time"]
    except KeyError:
        return JsonResponse({"error": "stale_session"}, status=400)

    session_status["time_of_last_status_check"] = time.time()

    save_complete = False
    saveRetries = 0
    while not save_complete:
        try:
            session_status.save()
            save_complete = True
        except Exception as e:
            time.sleep(0.1)
            saveRetries += 1
            if saveRetries > 100:
                raise e

    db.connections.close_all()
    close_old_connections()

    loadavg = platform_compat.get_loadavg()
    return JsonResponse({
        "completed": False,
        "currentStatus": currentStatus,
        "elapsed": ConvertSecondsToHMS(time.time() - startTime),
        "loadavg": list(loadavg),
    })


@cache_control(no_cache=True)
@ratelimit(key="ip", rate="12/m", block=False)
def LongRunningProcessView(
    request, inDimensionality, inEquationFamilyName="", inEquationName=""
):  # from urls.py, inDimensionality can only be '1', '2' or '3'
    import os, sys, time

    if -1 != request.path.find("FitEquation__F__/") or -1 != request.path.find(
        "Equation/"
    ):  # redundant but explicit
        if -1 != request.path.find("UserDefinedFunction"):
            LRP = LongRunningProcess.FitUserDefinedFunction.FitUserDefinedFunction()
        elif -1 != request.path.find("User-Selectable Polyfunctional"):
            LRP = LongRunningProcess.FitUserSelectablePolyfunctional.FitUserSelectablePolyfunctional()
        elif -1 != request.path.find("User-Selectable Polynomial"):
            LRP = LongRunningProcess.FitUserSelectablePolynomial.FitUserSelectablePolynomial()
        elif -1 != request.path.find("User-Customizable Polynomial"):
            LRP = LongRunningProcess.FitUserCustomizablePolynomial.FitUserCustomizablePolynomial()
        elif -1 != request.path.find("User-Selectable Rational"):
            LRP = (
                LongRunningProcess.FitUserSelectableRational.FitUserSelectableRational()
            )
        elif -1 != request.path.find("Spline"):
            LRP = LongRunningProcess.FitSpline.FitSpline()
        else:
            LRP = LongRunningProcess.FitOneEquation.FitOneEquation()
    elif -1 != request.path.find("CharacterizeData/"):
        LRP = LongRunningProcess.CharacterizeData.CharacterizeData()
    elif -1 != request.path.find("StatisticalDistributions/"):
        LRP = LongRunningProcess.StatisticalDistributions.StatisticalDistributions()
    elif -1 != request.path.find("FunctionFinder__"):
        LRP = LongRunningProcess.FunctionFinder.FunctionFinder()
    elif -1 != request.path.find("FunctionFinderResults/"):
        if request.method != "GET":  # send an error message
            return HttpResponse(
                "The function finder results view was called incorrectly."
            )
        if "RANK" not in list(request.GET.keys()):  # send an error message
            return HttpResponse(
                "The function finder results view was not called correctly."
            )
        try:
            rank = int(request.GET["RANK"])
        except:
            return HttpResponse("Incorrect call to function finder results view.")
        if rank < 1 or rank > 10000000:  # must be between 1 and 10 million
            return HttpResponse("Call to function finder results view was incorrect.")
        LRP = LongRunningProcess.FunctionFinderResults.FunctionFinderResults()
        LRP.rank = rank

    else:
        return HttpResponse("I could not understand the web request.")

    #####################################################################
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    #####################################################################

    LRP.inEquationName = urllib.parse.unquote(inEquationName)
    LRP.inEquationFamilyName = urllib.parse.unquote(inEquationFamilyName)
    LRP.dimensionality = int(inDimensionality)

    if CommonToAllViews(
        request
    ):  # any referrer blocks or web request checks processed here
        raise django.http.Http404

    if "session_key_status" not in list(request.session.keys()):
        # sometimes database is momentarily locked, so retry on exception to mitigate
        s = SessionStore()
        save_complete = False
        saveRetries = 0
        while not save_complete:
            try:
                s.save()
                save_complete = True
            except Exception as e:
                time.sleep(0.1)  # wait 1/10 second before retry
                saveRetries += 1  # increment retry count
                if saveRetries > 100:  # 10 per second * 10 seconds
                    raise e  # re-raise exception from save operation

        db.connections.close_all()
        close_old_connections()

        request.session["session_key_status"] = s.session_key
    LRP.session_key_status = request.session["session_key_status"]

    if "session_key_data" not in list(request.session.keys()):
        # sometimes database is momentarily locked, so retry on exception to mitigate
        s = SessionStore()
        save_complete = False
        saveRetries = 0
        while not save_complete:
            try:
                s.save()
                save_complete = True
            except Exception as e:
                time.sleep(0.1)  # wait 1/10 second before retry
                saveRetries += 1  # increment retry count
                if saveRetries > 100:  # 10 per second * 10 seconds
                    raise e  # re-raise exception from save operation

        db.connections.close_all()
        close_old_connections()

        request.session["session_key_data"] = s.session_key
    LRP.session_key_data = request.session["session_key_data"]

    if "session_key_functionfinder" not in list(request.session.keys()):
        # sometimes database is momentarily locked, so retry on exception to mitigate
        s = SessionStore()
        save_complete = False
        saveRetries = 0
        while not save_complete:
            try:
                s.save()
                save_complete = True
            except Exception as e:
                time.sleep(0.1)  # wait 1/10 second before retry
                saveRetries += 1  # increment retry count
                if saveRetries > 100:  # 10 per second * 10 seconds
                    raise e  # re-raise exception from save operation

        db.connections.close_all()
        close_old_connections()

        request.session["session_key_functionfinder"] = s.session_key
    LRP.session_key_functionfinder = request.session["session_key_functionfinder"]

    # if this is not a POST, send an interface if needed
    if LRP.userInterfaceRequired:
        if request.method != "POST":
            request.session["cookie_test"] = 1
            try:
                return render(
                    request,
                    LRP.interfaceString,
                    LRP.CreateUnboundInterfaceForm(request),
                )
                # return render_to_response(LRP.interfaceString, LRP.CreateUnboundInterfaceForm(request))
            except:
                return HttpResponse(
                    repr(sys.exc_info()[0]) + "<br>" + repr(sys.exc_info()[1])
                )

    if "cookie_test" not in list(request.session.keys()):
        return HttpResponse(
            "This web site requires a temporary session cookie.  Please enable session cookies (or reload the home page) and try again."
        )

    if LRP.userInterfaceRequired:
        try:
            LRP.CreateBoundInterfaceForm(request)
        except:
            return HttpResponse(str(sys.exc_info()[0]) + str(sys.exc_info()[1]))
        if not LRP.boundForm.is_valid():
            LRP.items_to_render = {}
            LRP.items_to_render["mainForm"] = LRP.boundForm
            LRP.items_to_render["EvaluateAtAPointForm"] = LRP.evaluationForm
            return render(request, "zunzun/invalid_form_data.html", LRP.items_to_render)

    returnString = LRP.TransferFormDataToDataObject(request)
    if returnString:
        return HttpResponse(returnString)

    if -1 == request.path.find("FunctionFinderResults/") and LRP.equationInstance:
        errorString = LRP.CheckDataForZeroAndPositiveAndNegative()
        if errorString:
            return render(request, "zunzun/generic_error.html", {"error": errorString})

    LRP.SetInitialStatusDataIntoSessionVariables(request)

    # sometimes database is momentarily locked, so retry on exception to mitigate
    s = request.session
    save_complete = False
    saveRetries = 0
    while not save_complete:
        try:
            s.save()
            save_complete = True
        except Exception as e:
            time.sleep(0.1)  # wait 1/10 second before retry
            saveRetries += 1  # increment retry count
            if saveRetries > 100:  # 10 per second * 10 seconds
                raise e  # re-raise exception from save operation

    db.connections.close_all()
    close_old_connections()

    # Build the picklable payload in the parent, then hand it to a spawned
    # child process. Spawn (vs fork) is mandatory on Windows and safer on
    # Linux under a multi-threaded WSGI server like Waitress.
    payload = LRP.build_child_payload()

    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=_run_fit_child, args=(payload,), daemon=False)
    child.start()

    # using HTTP_HOST allows dev server
    return HttpResponseRedirect(
        "http://" + request.META["HTTP_HOST"] + "/StatusAndResults/"
    )


@cache_control(no_cache=True)
@ratelimit(key="ip", rate="12/m", block=False)
def FeedbackView(request):
    import datetime
    import os, sys, time

    if CommonToAllViews(
        request
    ):  # any referrer blocks or web request checks processed here
        raise django.http.Http404

    if request.method == "POST":
        try:
            form = forms.FeedbackForm(request.POST)
        except:
            time.sleep(1.0)
            form = forms.FeedbackForm(request.POST)
        if not form.is_valid():  # validators added, see form definition
            items_to_render = {}
            items_to_render["mainForm"] = form
            return render(request, "zunzun/invalid_form_data.html", items_to_render)
        msg = (
            "Email from "
            + form.cleaned_data["emailAddress"]
            + "\n\nAt "
            + str(datetime.datetime.now())
            + "\n\n"
            + form.cleaned_data["feedbackText"]
        )
        if settings.FEEDBACK_EMAIL_ADDRESS:
            EmailMessage(
                "ZunZunNG Feedback Form", msg, to=[settings.FEEDBACK_EMAIL_ADDRESS]
            ).send()

        return render(request, "zunzun/feedback_reply.html", {})
    else:  # not a POST
        return HttpResponseRedirect("/")


@cache_page(60 * 60)  # 60 minutes
@ratelimit(key="ip", rate="12/m", block=False)
def HomePageView(request):
    import os, sys, time

    # only allow GET for this view
    if request.method != "GET":
        return HttpResponse("I am not able to process your request.")

    # housekeeping tasks, perform in separate process so
    # that actual home page generation time is not impacted
    db.connections.close_all()
    close_old_connections()
    ctx = multiprocessing.get_context("spawn")
    ctx.Process(
        target=_housekeeping_child,
        args=(settings.TEMP_FILES_DIR, settings.MAX_TEMP_DIR_SIZE_IN_MBYTES),
        daemon=True,
    ).start()

    # parent process, start code for view generation
    if CommonToAllViews(
        request
    ):  # any referrer blocks or web request checks processed here
        raise django.http.Http404

    request.session["cookie_test"] = 1

    items_to_render = {}
    items_to_render["dim_to_spline_list"] = [
        ["2", pyeq3.Models_2D.Spline.Spline()],
        ["3", pyeq3.Models_3D.Spline.Spline()],
    ]
    items_to_render["dim_to_map_list"] = [
        ["2", GetEquationInfoDictionary(2, "Standard")],
        ["3", GetEquationInfoDictionary(3, "Standard")],
    ]
    items_to_render["header_text"] = "ZunZunNG"
    items_to_render["subtitle_text"] = "Online Curve Fitting and Surface Fitting"
    items_to_render["feedbackForm"] = forms.FeedbackForm()
    items_to_render["loadavg"] = platform_compat.get_loadavg()

    return render(request, "zunzun/home_page.html", items_to_render)


@cache_control(no_cache=True)
@ratelimit(key="ip", rate="12/m", block=False)
def AllEquationsView(
    request, inDimensionality, inAllOrStandardOnly
):  # from urls.py, inDimensionality can only be '2' or '3'
    import os, sys, time

    # only allow GET for this view
    if request.method != "GET":
        return HttpResponse("I am not able to process your request.")

    if CommonToAllViews(
        request
    ):  # any referrer blocks or web request checks processed here
        raise django.http.Http404

    items_to_render = {}

    if "2" == inDimensionality:
        items_to_render["sortedEquationClassPropertiesList"] = (
            GetEquationInfoDictionary(2, inAllOrStandardOnly)
        )
    else:
        items_to_render["sortedEquationClassPropertiesList"] = (
            GetEquationInfoDictionary(3, inAllOrStandardOnly)
        )

    items_to_render["header_text"] = "ZunZunNG"
    if inAllOrStandardOnly == "All":
        items_to_render["subtitle_text"] = (
            "List Of All " + inDimensionality + "D Equations"
        )
    else:
        items_to_render["subtitle_text"] = (
            "List Of All Standard " + inDimensionality + "D Equations"
        )

    items_to_render["dimensionality"] = inDimensionality

    return render(request, "zunzun/list_all_equations.html", items_to_render)


def GetEquationInfoDictionary(inDimensionality, inAllOrStandardOnly):
    import inspect

    if inDimensionality == 2:
        submodules = inspect.getmembers(pyeq3.Models_2D)
    else:
        submodules = inspect.getmembers(pyeq3.Models_3D)

    submoduleNameList = []
    for submodule in submodules:
        if inspect.ismodule(submodule[1]):
            submoduleNameList.append(submodule[0])
    submoduleNameList.sort()

    if inAllOrStandardOnly == "Standard":
        extendedNameList = ["Default", "Offset", "PlusLine", "PlusPlane"]
    else:
        extendedNameList = pyeq3.ExtendedVersionHandlers.extendedVersionHandlerNameList

    allEquationClassPropertiesList = []

    for submoduleName in submoduleNameList:
        for submodule in submodules:
            if inspect.ismodule(submodule[1]):
                if submodule[0] != submoduleName:
                    continue
                for extendedName in extendedNameList:
                    for equationClass in inspect.getmembers(submodule[1]):
                        if inspect.isclass(equationClass[1]):
                            if (
                                equationClass[1].splineFlag
                                or equationClass[1].userDefinedFunctionFlag
                            ):
                                continue

                            # special case as user can select an "offset" flag on the user interface
                            if (
                                (
                                    equationClass[0] == "UserSelectableRational"
                                    or equationClass[0]
                                    == "UserSelectablePolyfunctional"
                                )
                                and extendedName != "Default"
                            ):  # only need to see default versions of these
                                continue

                            try:
                                equation = equationClass[1]("SSQABS", extendedName)
                            except:
                                continue

                            extendedSuffix = equation.extendedVersionHandler.__class__.__name__.split(
                                "_"
                            )[1]

                            if (
                                equation.autoGenerateOffsetForm == False
                                and -1 != extendedSuffix.find("Offset")
                            ):
                                continue
                            if (
                                equation.autoGeneratePlusLineForm == False
                                and -1 != extendedSuffix.find("PlusLine")
                            ):
                                continue
                            if (
                                equation.autoGeneratePlusPlaneForm == False
                                and -1 != extendedSuffix.find("PlusPlane")
                            ):
                                continue
                            if (
                                equation.autoGenerateReciprocalForm == False
                                and -1 != extendedSuffix.find("Reciprocal")
                            ):
                                continue
                            if (
                                equation.autoGenerateInverseForms == False
                                and -1 != extendedSuffix.find("Inverse")
                            ):
                                continue
                            if (
                                equation.autoGenerateGrowthAndDecayForms == False
                                and -1 != extendedSuffix.find("Growth")
                            ):
                                continue
                            if (
                                equation.autoGenerateGrowthAndDecayForms == False
                                and -1 != extendedSuffix.find("Decay")
                            ):
                                continue

                            temp = ClassForAttachingProperties()

                            temp.submoduleName = submoduleName
                            temp.extendedName = extendedName
                            temp.name = equation.GetDisplayName()
                            temp.HTML = (
                                '<span class="math">'
                                + equation.GetDisplayHTML()
                                + "</span>"
                            )
                            temp.webCitationLink = equation.webReferenceURL
                            temp.url_quote_name = urllib.parse.quote(temp.name)
                            if "<BR>" in temp.HTML.upper():
                                temp.multiLineHtmlFlag = True

                            # add item to dictionary
                            allEquationClassPropertiesList.append(temp)

    allEquationClassPropertiesList.sort(
        key=keyFunctionToSortListOfEquationPropertyClasses
    )
    for index in range(1, len(allEquationClassPropertiesList)):
        if index == 1:
            allEquationClassPropertiesList[index - 1].firstItemInSubmoduleFlag = True
        else:
            if (
                allEquationClassPropertiesList[index].submoduleName
                != allEquationClassPropertiesList[index - 1].submoduleName
            ):
                allEquationClassPropertiesList[index - 1].lastItemInSubmoduleFlag = True
                allEquationClassPropertiesList[index].firstItemInSubmoduleFlag = True
                allEquationClassPropertiesList[
                    index - 1
                ].lastItemInExtendedNameFlag = True
                allEquationClassPropertiesList[index].firstItemInExtendedNameFlag = True

        if index == 1:
            allEquationClassPropertiesList[index - 1].firstItemInExtendedNameFlag = True
        else:
            if (
                allEquationClassPropertiesList[index].extendedName
                != allEquationClassPropertiesList[index - 1].extendedName
            ):
                allEquationClassPropertiesList[
                    index - 1
                ].lastItemInExtendedNameFlag = True
                allEquationClassPropertiesList[index].firstItemInExtendedNameFlag = True

        allEquationClassPropertiesList[
            len(allEquationClassPropertiesList) - 1
        ].lastItemInSubmoduleFlag = True
        allEquationClassPropertiesList[
            len(allEquationClassPropertiesList) - 1
        ].lastItemInExtendedNameFlag = True

    return allEquationClassPropertiesList


def CommonToAllViews(request):

    # Reap any completed multiprocessing children so they don't linger.
    # No-op on Windows (no zombies), proper cleanup on Unix.
    platform_compat.reap_completed_children()

    ip = request.META.get("REMOTE_ADDR")
    if ip in []:
        raise django.http.Http404

    if request.META["REQUEST_METHOD"] not in ["GET", "POST"]:
        raise django.http.Http404

    # django-ratelimit sets request.limited=True when the caller
    # exceeds the rate (with block=False, the decorator does not raise).
    was_limited = getattr(request, "limited", False)
    if was_limited:
        time.sleep(5.0)  # sleep for 5 seconds to slow down slammers

    return False  # all OK


class ClassForAttachingProperties:
    multiLineHtmlFlag = False
    moduleName = "moduleName"
    name = "name"
    extendedName = "extendedName"
    HTML = "HTML"
    webCitationLink = ""
    url_quote_name = "url_quote_name"
    firstItemInSubmoduleFlag = False
    firstItemInExtendedNameFlag = False
    lastItemInSubmoduleFlag = False
    lastItemInExtendedNameFlag = False


def keyFunctionToSortListOfEquationPropertyClasses(item):
    # logic is to sort for display in this order:
    # 1) submodule name
    # 2) extendedModuleName - Default first, then Offset, then others
    # 3) name

    # underscores sort first
    extendedName = item.extendedName
    if extendedName == "Default":
        extendedName = "_Default"
    if extendedName == "Offset":
        extendedName = "__Offset"
    if extendedName == "PlusPlane":  # 3D only
        extendedName = "___PlusPlane"
    if extendedName == "PlusLine":  # 2D only
        extendedName = "___PlusLine"

    return item.submoduleName + extendedName + item.name
