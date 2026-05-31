import logging
import multiprocessing
import os
import time
import urllib.parse

import django.http  # to raise 404's
import numpy
import pyeq3
import scipy.interpolate
from django import db
from django.contrib.sessions.backends.db import SessionStore
from django.core.mail import EmailMessage
from django.db import close_old_connections
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control, cache_page
from django_ratelimit.decorators import ratelimit

import settings

from . import LongRunningProcess, forms, middleware, platform_compat
from .LongRunningProcess.child_payload import _run_fit_child
from .session_helpers import save_with_retry

_logger = logging.getLogger(__name__)


def _housekeeping_child(temp_dir: str, max_size_mb: int) -> None:
    """Top-level entrypoint for the HomePageView housekeeping fork.

    Must be module-level (not nested) for spawn to pickle it.
    Clears expired sessions and trims temp/ when it exceeds
    max_size_mb.
    """
    # Spawn starts a fresh interpreter that does NOT inherit the parent's
    # Django bootstrap (same constraint _run_fit_child documents). Without
    # django.setup() here, the first ORM/session call below raises
    # AppRegistryNotReady. setup() is idempotent (a safe near-no-op when the
    # registry is already populated, e.g. under pytest).
    import logging

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
    django.setup()

    from django.contrib.sessions.backends.db import SessionStore as _SessionStore

    # Each housekeeping job runs in its OWN try/except so a failure in one
    # (e.g. a transient SQLite lock on the DB-backed jobs) does not skip the
    # others. In particular the temp-dir prune — the job that bounds disk to
    # MAX_TEMP_DIR_SIZE_IN_MBYTES — must still run if the session-clear or the
    # LRPStatus sweep raises. Failures are logged rather than silently
    # swallowed so a recurring fault surfaces in the logs instead of presenting
    # as housekeeping that mysteriously stopped working.
    try:
        _SessionStore().clear_expired()
    except Exception:
        logging.exception("Housekeeping: clear_expired() failed")

    # Reclaim LRPStatus rows whose user session has expired without a new
    # dispatch (delete-prior-row on dispatch handles the common case).
    try:
        from zunzun.models import LRPStatus as _LRPStatus

        cutoff = time.time() - settings.SESSION_COOKIE_AGE
        _LRPStatus.objects.filter(last_status_check__lt=cutoff, start_time__lt=cutoff).delete()
    except Exception:
        logging.exception("Housekeeping: LRPStatus age-sweep failed")

    # Trim temp/ when it exceeds max_size_mb.
    try:
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
                        # A single locked/vanished file shouldn't stop the
                        # prune; log at debug and move to the next candidate.
                        logging.debug(
                            "Housekeeping: could not remove %s", fileItem[2], exc_info=True
                        )
                else:
                    break
    except Exception:
        logging.exception("Housekeeping: temp-dir prune failed")


@cache_control(no_cache=True)
@ratelimit(key="ip", rate="12/m", block=False)
@middleware.rate_limit_sleep
def EvaluateAtAPointView(request):
    import os
    import sys
    import time

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
        equation.xPolynomialOrder = LRP.LoadItemFromSessionStore("data", "xPolynomialOrder")
        equation.yPolynomialOrder = LRP.LoadItemFromSessionStore("data", "yPolynomialOrder")
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
        equation.polynomial2DFlags = LRP.LoadItemFromSessionStore("data", "polynomial2DFlags")
    else:
        equation.fittingTarget = LRP.LoadItemFromSessionStore("data", "fittingTarget")

    # solvedCoefficients round-trips through the session as a JSON list
    # (NumpySessionSerializer coerces the numpy array at save time). pyeq3's
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
            pointValue = pointValue[0]  # spline evaluation was returning scalar and not array
        except:
            pass
        if pointValue < 1.0e300 and pointValue > -1.0e300:
            pointValueAsString = "evaluates to <b>" + str(pointValue) + "</b>"
        else:
            pointValueAsString = (
                "Evaluation was outside numeric bounds of +/- 1.0E300, please check the data."
            )
    except:
        exceptionString = str(sys.exc_info()[0]) + "  " + str(sys.exc_info()[1]) + "\n"
        exceptionString += inEquationFamilyName + "\n"
        exceptionString += inEquationName + "\n"
        exceptionString += str(equation.solvedCoefficients) + "\n"
        exceptionString += str(equation.dataCache.allDataCacheDictionary["IndependentData"])
        # Full detail (exception type/text, equation internals, the data-cache
        # dump) goes to the server log and the admin email only. The user gets a
        # generic message — echoing exceptionString into the response is the
        # CodeQL py/stack-trace-exposure finding.
        _logger.exception("Exception evaluating equation at a point")
        pointValueAsString = "Exception in evaluation, please check the data."
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


def _finalize_row_if_child_dead(row) -> bool:
    """Terminal backstop for a fit child that died WITHOUT finalizing its row.

    The normal terminal paths (success, abort, the _run_fit_child exception
    handler) set completed=True and clear process_id. But a child killed by
    SIGKILL / OOM / segfault — or one whose terminal LRPStatus write itself
    failed under sustained DB lock past busy_timeout — leaves the row showing an
    in-progress fit forever (process_id set, completed False). The poll loop
    would then never end and the per-user is_active gate would block the user's
    retry for up to 300s. This is the one unrecoverable-write gap the LRPStatus
    busy_timeout (no retry loop, by design) cannot close on the writer side, so
    it is closed here on the reader side — which additionally catches every
    no-handler-ran crash (SIGKILL/OOM/segfault) a writer-side retry never could.

    Two abandonment shapes are handled:

      1. process_id SET but its owning pid is no longer alive on this host —
         the common SIGKILL/OOM/segfault-mid-fit case; probe the pid.
      2. process_id NEVER written (still 0) but the row is well past the 60s
         pending window — the child died (or failed to spawn) during early
         startup, BEFORE PerformAllWork's first ``process_id`` write. The pid
         probe can't see this (there is no pid to probe), so without this
         branch such a row polls forever. A healthy child writes its pid
         within a few seconds of dispatch — well inside 60s — so this never
         races a slow-but-live startup. 60s matches the per-user gate's
         is_pending bound, keeping the two views of "pending" consistent.

    If the row looks abandoned, mark it terminal so StatusView serves the
    "no results" page and the gate releases. Mutates the passed-in ``row`` in
    place so the caller's subsequent ``row.completed`` check sees the update.
    Returns True iff it finalized. See platform_compat.pid_is_alive for the
    co-location and pid-reuse caveats.
    """
    if row.completed:
        return False
    if row.process_id:
        # Child claimed the row: a live pid means the fit is genuinely still
        # running, so leave it alone.
        if platform_compat.pid_is_alive(row.process_id):
            return False
    else:
        # No pid written yet: still within the pending window → assume the
        # child is just starting up and leave it alone (no pid to probe).
        if (time.time() - row.start_time) < 60:
            return False

    import logging

    logging.warning(
        "LRPStatus row %s looks abandoned (process_id=%s, no live owner or no "
        "pid written within the pending window); marking it terminal so the "
        "poll loop ends",
        row.pk,
        row.process_id,
    )
    from zunzun.models import LRPStatus

    LRPStatus.objects.filter(pk=row.pk).update(
        process_id=0,
        completed=True,
        current_status="The fit process ended unexpectedly. Please try again.",
    )
    row.process_id = 0
    row.completed = True
    return True


@cache_control(no_cache=True)
def StatusView(request):
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.filter(pk=request.session.get("lrp_status_pk")).first()
    if row is None:
        return HttpResponse("I could not read your session data, please try again.")

    # Completion handoff: read, clear, serve file body OR HttpResponseRedirect.
    # Behavior unchanged from the original implementation (only the backing
    # store moved from the session blob to the LRPStatus row).
    if row.redirect_to_results:
        redirect = row.redirect_to_results
        LRPStatus.objects.filter(pk=row.pk).update(redirect_to_results="")

        db.connections.close_all()
        close_old_connections()

        if redirect.startswith(settings.TEMP_FILES_DIR):
            # encoding="utf-8" matches the writer in
            # RenderOutputHTMLToAFileAndSetStatusRedirect and
            # _run_fit_child's terminal-error fallback. Without it,
            # the default locale encoding (cp1252 on Windows) would
            # mis-decode any non-ASCII byte in the result HTML.
            with open(redirect, "r", encoding="utf-8") as f:
                s = f.read()
            return HttpResponse(s)
        else:
            return HttpResponseRedirect(redirect)

    # Backstop: a child that died without finalizing its row (SIGKILL / OOM /
    # crash, or a failed terminal write) is detected here and promoted to
    # terminal so the request takes the completed branch below instead of
    # falling through to the in-progress render forever.
    _finalize_row_if_child_dead(row)

    # Terminal without a deliverable redirect: the fit finished (completed=True
    # is the durable terminal flag) but there is nothing to serve — a mid-fit
    # crash whose error page could not be written, or a success whose redirect
    # was already served & cleared in another tab. Serve a terminal page so the
    # poll loop ends; without this the request falls through to the in-progress
    # render and StatusUpdateView (also keyed on completed) bounces the browser
    # back here indefinitely.
    if row.completed:
        return render(
            request,
            "zunzun/generic_error.html",
            {
                "error": "Your fit has finished, but there are no results to "
                "display — they may already have been shown in another tab, or "
                "an error prevented the results page from being created. Please "
                "run the fit again."
            },
        )

    # In-progress branch: render the template. Heartbeat write moved to
    # StatusUpdateView so there is a single owner of that side effect.
    loadavg = platform_compat.get_loadavg()
    return render(
        request,
        "zunzun/status.html",
        {
            "title_string": "ZunZunNG - Working on your fit",
            "header_text": "ZunZunNG",
            "currentStatus": row.current_status,
            "elapsed": ConvertSecondsToHMS(time.time() - row.start_time),
            "loadavg": list(loadavg),
            "coreCount": multiprocessing.cpu_count(),
            "parallelProcessCount": row.parallel_count,
        },
    )


@cache_control(no_cache=True)
def StatusUpdateView(request):
    """JSON polling endpoint for the status page.

    Returns the live status fields (currentStatus, elapsed, loadavg) as JSON.
    On completion, returns {"completed": True} and intentionally does NOT
    clear redirect_to_results — that's StatusView's job when the browser
    follows up.
    """
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.filter(pk=request.session.get("lrp_status_pk")).first()
    if row is None:
        # Matches StatusView's defensive handling: missing pk, expired
        # session, or never dispatched. JS treats any non-2xx as "wait and
        # retry" so this is graceful.
        return JsonResponse({"error": "stale_session"}, status=400)

    # Backstop for a child that died without finalizing — see
    # _finalize_row_if_child_dead. Promotes a dead-pid in-progress row to
    # terminal so the completion check below returns instead of heartbeating
    # forever against a row whose owner is already gone.
    _finalize_row_if_child_dead(row)

    # Completion: report immediately. `completed` is the durable terminal
    # signal — every terminal path (success, abort, mid-fit crash) sets it,
    # and unlike redirect_to_results it survives StatusView clearing the
    # redirect on serve. Keying off it (not the redirect) means a fit that
    # finished without a deliverable redirect — a crash whose error page could
    # not be linked, or a result already served & cleared in another tab —
    # still ends the poll instead of heartbeating forever. Do NOT clear the
    # redirect; that's StatusView's job when the browser follows up.
    if row.completed or row.redirect_to_results:
        return JsonResponse({"completed": True})

    # Heartbeat write: the only RECURRING writer of last_status_check (it is
    # also stamped once at dispatch in LongRunningProcessView). The per-user
    # gate and CheckIfStillUsed read it for liveness.
    LRPStatus.objects.filter(pk=row.pk).update(last_status_check=time.time())

    db.connections.close_all()
    close_old_connections()

    loadavg = platform_compat.get_loadavg()
    return JsonResponse(
        {
            "completed": False,
            "currentStatus": row.current_status,
            "elapsed": ConvertSecondsToHMS(time.time() - row.start_time),
            "loadavg": list(loadavg),
            "parallelProcessCount": row.parallel_count,
        }
    )


@cache_control(no_cache=True)
@ratelimit(key="ip", rate="12/m", block=False)
@middleware.rate_limit_sleep
def LongRunningProcessView(
    request, inDimensionality, inEquationFamilyName="", inEquationName=""
):  # from urls.py, inDimensionality can only be '1', '2' or '3'
    import os
    import sys
    import time

    if -1 != request.path.find("FitEquation__F__/") or -1 != request.path.find(
        "Equation/"
    ):  # redundant but explicit
        if -1 != request.path.find("UserDefinedFunction"):
            LRP = LongRunningProcess.FitUserDefinedFunction.FitUserDefinedFunction()
        elif -1 != request.path.find("User-Selectable Polyfunctional"):
            LRP = (
                LongRunningProcess.FitUserSelectablePolyfunctional.FitUserSelectablePolyfunctional()
            )
        elif -1 != request.path.find("User-Selectable Polynomial"):
            LRP = LongRunningProcess.FitUserSelectablePolynomial.FitUserSelectablePolynomial()
        elif -1 != request.path.find("User-Customizable Polynomial"):
            LRP = LongRunningProcess.FitUserCustomizablePolynomial.FitUserCustomizablePolynomial()
        elif -1 != request.path.find("User-Selectable Rational"):
            LRP = LongRunningProcess.FitUserSelectableRational.FitUserSelectableRational()
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
            return HttpResponse("The function finder results view was called incorrectly.")
        if "RANK" not in list(request.GET.keys()):  # send an error message
            return HttpResponse("The function finder results view was not called correctly.")
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

    # Per-user "one fit at a time" cap. When ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER
    # is False (recommended for public deployments), reject a second fit POST
    # from the same session if the user's PRIOR LRPStatus row shows an active
    # process_id with a recent status-check heartbeat. Check happens BEFORE
    # form validation so the user gets a fast "in progress" response rather
    # than being routed through form processing first. This reads the pk set
    # by a PRIOR dispatch — it must run BEFORE the create-row block below
    # overwrites request.session['lrp_status_pk'].
    if request.method == "POST" and not getattr(
        settings, "ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", True
    ):
        try:
            from zunzun.models import LRPStatus

            row = LRPStatus.objects.filter(pk=request.session.get("lrp_status_pk")).first()
            # Apply the dead-child backstop before judging the prior fit: a
            # child killed by SIGKILL/OOM/segfault (or one whose terminal write
            # failed) leaves the row process_id-set / completed-False with a
            # heartbeat that can stay fresh for up to 300s, which would block
            # this user's retry even though no fit is running. _finalize_row_if_
            # child_dead promotes such a row to terminal (process_id=0,
            # completed=True) in place, so the is_active/is_pending checks below
            # see the released state. Mirrors what the status views already do
            # on the poll path; without it the gate is the one place a provably-
            # dead fit still gates. (A live fit's pid passes the probe and is
            # left untouched, so genuine in-progress fits still block.)
            if row is not None:
                _finalize_row_if_child_dead(row)
            now = time.time()
            # Block if EITHER:
            #  - a child has written process_id and its heartbeat is fresh
            #    (within 300s — matches CheckIfStillUsed's abandoned-fit
            #    threshold so the gate stays consistent: if the system
            #    considers a fit alive, the cap blocks; once the system
            #    considers it abandoned, the cap allows replacement).
            #  - a fit was just dispatched (start_time recent) but the child
            #    hasn't yet written process_id — the race window between the
            #    parent creating the row and the child's first PerformAllWork
            #    status write (~50-500ms). start_time covers the pending
            #    window that the dispatch-id float used to cover. The 60s bound
            #    is a deliberately generous upper limit on that sub-second gap
            #    (slack absorbs a heavily-loaded box where the child's first
            #    status write is delayed); it debounces double-clicks, not
            #    long-running fits, which are caught by is_active instead. A completed
            #    fit is excluded via the explicit `completed` flag: start_time
            #    is NOT cleared on completion, so a fast (<60s) fit would
            #    otherwise falsely register as pending and block the next POST.
            #    The `completed` flag (set at every terminal write) is the
            #    "no longer in progress" signal — NOT redirect_to_results,
            #    which StatusView clears the moment it serves the result.
            # Missing row → no active fit → allow.
            # `not row.completed` guards the narrow window where a terminal
            # write set completed=True but the child died before clearing
            # process_id (e.g. killed between RenderOutputHTML's completed=True
            # write and PerformAllWork's process_id=0 clear). A finished fit —
            # result already deliverable — must not register as an active fit
            # and block the user's next POST for the 300s heartbeat window.
            is_active = (
                bool(row)
                and row.process_id
                and (now - row.last_status_check) < 300
                and not row.completed
            )
            is_pending = (
                bool(row)
                and (now - row.start_time) < 60
                and not row.process_id
                and not row.completed
            )
            if is_active or is_pending:
                return HttpResponse(
                    "A fit is already in progress for your session. "
                    "Please wait for it to complete or "
                    "<a href='/StatusAndResults/'>view its status</a>."
                )
        except Exception:
            # Row read failure → fail OPEN (allow the new fit): the cap is soft
            # anti-abuse, not a correctness invariant, so a transient SQLite
            # lock shouldn't block a legitimate user. Log it, though — a
            # PERSISTENT fault would otherwise silently defeat the cap entirely
            # with no operator signal.
            import logging

            logging.exception("Per-user fit gate row read failed; allowing new fit")

    if "session_key_data" not in list(request.session.keys()):
        # sometimes database is momentarily locked, so retry on exception to mitigate
        s = SessionStore()
        save_with_retry(s)  # re-raise exception from save operation

        db.connections.close_all()
        close_old_connections()

        request.session["session_key_data"] = s.session_key
    LRP.session_key_data = request.session["session_key_data"]

    if "session_key_functionfinder" not in list(request.session.keys()):
        # sometimes database is momentarily locked, so retry on exception to mitigate
        s = SessionStore()
        save_with_retry(s)  # re-raise exception from save operation

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
                _logger.exception("Failed to render unbound interface form")
                return HttpResponse(
                    "An error occurred while building the form. "
                    "Please reload the home page and try again."
                )

    if "cookie_test" not in list(request.session.keys()):
        return HttpResponse(
            "This web site requires a temporary session cookie.  Please enable session cookies (or reload the home page) and try again."
        )

    if LRP.userInterfaceRequired:
        try:
            LRP.CreateBoundInterfaceForm(request)
        except:
            _logger.exception("CreateBoundInterfaceForm raised")
            return HttpResponse(
                "An error occurred while processing your input. "
                "Please check the form and try again."
            )
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

    # Per-dispatch status row. Create a fresh row and point the session at it.
    # The child writes only this row, so there is no shared cell to race on.
    # Autocommit makes the row durable before multiprocessing.Process.start()
    # spawns the child.
    #
    # Delete the user's PRIOR row only when concurrent fits are DISALLOWED.
    # Rationale: a missing row is the supersession signal CheckIfStillUsed uses
    # to abort an abandoned child (it raises _ReportsPipelineAborted at the next
    # heartbeat). When ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER is True (the
    # default), the prior fit is allowed to keep running, so deleting its row
    # would make ITS CheckIfStillUsed see a missing row and tear the
    # still-wanted fit down — breaking the concurrent-fit promise. So in
    # concurrent-allowed mode we leave the prior row for the housekeeping
    # age-sweep (it's unreferenced once the pointer moves below). In
    # concurrent-disallowed mode, reaching this block means the per-user gate
    # already judged the prior fit stale or completed, so deleting it is the
    # intended supersession and the superseded child aborting is correct.
    from zunzun.models import LRPStatus

    old_pk = request.session.get("lrp_status_pk")
    if old_pk and not getattr(settings, "ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER", True):
        LRPStatus.objects.filter(pk=old_pk).delete()
    # Stamp last_status_check at dispatch (not only at the first poll) so the
    # per-user "one fit at a time" gate's is_active check — process_id set AND
    # (now - last_status_check) < 300 — holds for 300s even if the client never
    # polls (closed tab / script). Without this, last_status_check would stay
    # 0.0 until StatusUpdateView's first heartbeat, and a non-polling client
    # could bypass the cap ~0.5s after the child writes process_id. Restores
    # the old SetInitialStatusDataIntoSessionVariables semantics where dispatch
    # time doubled as the first heartbeat.
    now = time.time()
    status_row = LRPStatus.objects.create(
        start_time=now,
        last_status_check=now,
        current_status="Initializing",
    )
    request.session["lrp_status_pk"] = status_row.pk
    LRP.status_row_pk = status_row.pk

    LRP.SetInitialStatusDataIntoSessionVariables(request)

    # sometimes database is momentarily locked, so retry on exception to mitigate
    s = request.session
    save_with_retry(s)  # re-raise exception from save operation

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
    return HttpResponseRedirect("http://" + request.META["HTTP_HOST"] + "/StatusAndResults/")


@cache_control(no_cache=True)
@ratelimit(key="ip", rate="12/m", block=False)
@middleware.rate_limit_sleep
def FeedbackView(request):
    import datetime
    import os
    import sys
    import time

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
            EmailMessage("ZunZunNG Feedback Form", msg, to=[settings.FEEDBACK_EMAIL_ADDRESS]).send()

        return render(request, "zunzun/feedback_reply.html", {})
    else:  # not a POST
        return HttpResponseRedirect("/")


@cache_page(60 * 60)  # 60 minutes
@ratelimit(key="ip", rate="12/m", block=False)
@middleware.rate_limit_sleep
def HomePageView(request):
    import os
    import sys
    import time

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
@middleware.rate_limit_sleep
def AllEquationsView(
    request, inDimensionality, inAllOrStandardOnly
):  # from urls.py, inDimensionality can only be '2' or '3'
    import os
    import sys
    import time

    # only allow GET for this view
    if request.method != "GET":
        return HttpResponse("I am not able to process your request.")

    items_to_render = {}

    if "2" == inDimensionality:
        items_to_render["sortedEquationClassPropertiesList"] = GetEquationInfoDictionary(
            2, inAllOrStandardOnly
        )
    else:
        items_to_render["sortedEquationClassPropertiesList"] = GetEquationInfoDictionary(
            3, inAllOrStandardOnly
        )

    items_to_render["header_text"] = "ZunZunNG"
    if inAllOrStandardOnly == "All":
        items_to_render["subtitle_text"] = "List Of All " + inDimensionality + "D Equations"
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
                                    or equationClass[0] == "UserSelectablePolyfunctional"
                                )
                                and extendedName != "Default"
                            ):  # only need to see default versions of these
                                continue

                            try:
                                equation = equationClass[1]("SSQABS", extendedName)
                            except:
                                continue

                            extendedSuffix = (
                                equation.extendedVersionHandler.__class__.__name__.split("_")[1]
                            )

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
                                '<span class="math">' + equation.GetDisplayHTML() + "</span>"
                            )
                            temp.webCitationLink = equation.webReferenceURL
                            temp.url_quote_name = urllib.parse.quote(temp.name)
                            if "<BR>" in temp.HTML.upper():
                                temp.multiLineHtmlFlag = True

                            # add item to dictionary
                            allEquationClassPropertiesList.append(temp)

    allEquationClassPropertiesList.sort(key=keyFunctionToSortListOfEquationPropertyClasses)
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
                allEquationClassPropertiesList[index - 1].lastItemInExtendedNameFlag = True
                allEquationClassPropertiesList[index].firstItemInExtendedNameFlag = True

        if index == 1:
            allEquationClassPropertiesList[index - 1].firstItemInExtendedNameFlag = True
        else:
            if (
                allEquationClassPropertiesList[index].extendedName
                != allEquationClassPropertiesList[index - 1].extendedName
            ):
                allEquationClassPropertiesList[index - 1].lastItemInExtendedNameFlag = True
                allEquationClassPropertiesList[index].firstItemInExtendedNameFlag = True

        allEquationClassPropertiesList[
            len(allEquationClassPropertiesList) - 1
        ].lastItemInSubmoduleFlag = True
        allEquationClassPropertiesList[
            len(allEquationClassPropertiesList) - 1
        ].lastItemInExtendedNameFlag = True

    return allEquationClassPropertiesList


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
