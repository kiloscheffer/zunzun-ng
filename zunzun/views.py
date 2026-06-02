import logging
import multiprocessing
import os
import time
import urllib.parse

import numpy
import pyeq3
import scipy.interpolate
from django import db
from django.core.mail import EmailMessage
from django.db import InterfaceError, OperationalError, close_old_connections
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control, cache_page
from django_ratelimit.decorators import ratelimit

import settings

from . import LongRunningProcess, forms, middleware, platform_compat
from .LongRunningProcess.child_payload import _run_fit_child
from .session_helpers import save_with_retry

_logger = logging.getLogger(__name__)

# Heartbeat staleness threshold in seconds. A row whose last_status_check is
# older than this is considered abandoned by the per-user cap and the
# probe-on-demand block. MUST stay in sync with CheckIfStillUsed's 300s
# abandonment window in StatusMonitoredLongRunningProcessPage.
_HEARTBEAT_STALE_SECS = 300


def _sweep_aged_rows():
    """Reclaim LRPStatus rows whose session has expired (both timestamps older
    than SESSION_COOKIE_AGE). EXCLUDES completed FILE-BACKED results
    (state=TERMINAL with redirect_to_results under TEMP_FILES_DIR): their
    retention is tied to the temp/ artifact via _sweep_orphaned_terminal_rows
    (reaped when the size-bounded prune removes the file), so a shareable
    /Results/<token>/ link survives session expiry as documented. Abandoned
    in-progress rows, FunctionFinder URL-redirect results, and crashed
    empty-redirect rows are still age-reaped."""
    from django.conf import settings

    from zunzun.models import LRPStatus

    cutoff = time.time() - settings.SESSION_COOKIE_AGE
    LRPStatus.objects.filter(last_status_check__lt=cutoff, start_time__lt=cutoff).exclude(
        state=LRPStatus.State.TERMINAL,
        redirect_to_results__startswith=settings.TEMP_FILES_DIR,
    ).delete()


def _sweep_orphaned_terminal_rows():
    """Delete TERMINAL LRPStatus rows whose FILE-BACKED result was trimmed from
    temp/ (the cascade drops their LRPDispatchData). Keeps a shareable result
    page and its Evaluate button aging out together — the row tracks the file,
    which the temp-dir prune already bounds by MAX_TEMP_DIR_SIZE_IN_MBYTES.

    Only file-backed results (redirect_to_results under TEMP_FILES_DIR) are
    swept here. URL-redirect results (FunctionFinder, a /FunctionFinderResults/
    route, not a file) and empty redirects are left to the row age-sweep — a
    file-existence check would wrongly reap them.
    """
    from django.conf import settings

    from zunzun.models import LRPStatus

    temp_dir = settings.TEMP_FILES_DIR
    for row in LRPStatus.objects.filter(state=LRPStatus.State.TERMINAL).only(
        "id", "redirect_to_results"
    ):
        target = row.redirect_to_results
        if target and target.startswith(temp_dir) and not os.path.exists(target):
            row.delete()


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

    # Reclaim LRPStatus rows whose user session has expired. File-backed
    # TERMINAL results are excluded — their retention is tied to the temp/
    # artifact and they are reclaimed by _sweep_orphaned_terminal_rows instead,
    # so shareable /Results/<token>/ links survive past session expiry.
    try:
        _sweep_aged_rows()
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

    # Reclaim TERMINAL LRPStatus rows (and their cascaded LRPDispatchData) whose
    # file-backed result was removed by the temp-dir prune above. Runs after the
    # prune so newly-trimmed files are swept in the same housekeeping pass.
    # URL-redirect results (FunctionFinder) and empty redirects are NOT touched
    # here; they age out via the row age-sweep above.
    try:
        _sweep_orphaned_terminal_rows()
    except Exception:
        logging.exception("Housekeeping: orphaned-terminal-rows sweep failed")


@cache_control(no_cache=True)
@ratelimit(key="ip", rate="12/m", block=False)
@middleware.rate_limit_sleep
def EvaluateAtAPointView(request, token):
    import os
    import sys
    import time

    # only allow POST for this view
    if request.method != "POST":
        return HttpResponse("I am not able to process your request.")

    from zunzun.models import LRPStatus

    row = LRPStatus.objects.filter(result_token=token).first()
    if row is None:
        return HttpResponse("This result has expired.")
    LRP = LongRunningProcess.FittingBaseClass.FittingBaseClass()
    LRP.status_row_pk = row.pk

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
    handler) set state=TERMINAL and clear process_id. But a child killed by
    SIGKILL / OOM / segfault — or one whose terminal LRPStatus write itself
    failed under sustained DB lock past busy_timeout — leaves the row non-terminal
    forever (state still RUNNING or INITIALIZING, process_id possibly set). The
    poll loop would then never end and the per-user is_active gate would block the
    user's retry for up to 300s. This is the one unrecoverable-write gap the LRPStatus
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
    place so the caller's subsequent ``row.state`` check sees the update.
    Returns True iff it finalized. See platform_compat.pid_is_alive for the
    co-location and pid-reuse caveats.
    """
    from zunzun.models import LRPStatus

    if row.state == LRPStatus.State.TERMINAL:
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

    _logger.warning(
        "LRPStatus row %s looks abandoned (process_id=%s, no live owner or no "
        "pid written within the pending window); marking it terminal so the "
        "poll loop ends",
        row.pk,
        row.process_id,
    )
    LRPStatus.mark_terminal(
        row.pk,
        current_status="The fit process ended unexpectedly. Please try again.",
    )
    row.process_id = 0
    row.state = LRPStatus.State.TERMINAL
    return True


def _active_fit_counts(session_key, ip):
    """(per_session, per_ip) active fit counts: INITIALIZING/RUNNING rows with
    a fresh (<_HEARTBEAT_STALE_SECS) heartbeat. Mirrors CheckIfStillUsed's
    abandonment window so 'the system thinks it's alive' and 'the cap counts
    it' stay consistent."""
    from zunzun.models import LRPStatus

    fresh = time.time() - _HEARTBEAT_STALE_SECS
    base = LRPStatus.objects.exclude(state=LRPStatus.State.TERMINAL).filter(
        last_status_check__gte=fresh
    )
    per_session = base.filter(owner_session_key=session_key).count() if session_key else 0
    per_ip = base.filter(owner_ip=ip).count() if ip else 0
    return (per_session, per_ip)


def _load_owned_status_row(request, pk):
    """Return the LRPStatus row for `pk` only if it belongs to this session.

    Returns None for both "no such row" and "not your row" so callers can
    raise an identical 404 either way — a 404 that differs between the two
    leaks pk existence as an enumeration oracle (sequential pks are visible
    in the URL). The session cookie is the access boundary; the pk alone is
    useless without it.
    """
    from zunzun.models import LRPStatus

    row = LRPStatus.objects.filter(pk=pk).first()
    session_key = request.session.session_key
    if row is None or not row.is_owned_by(session_key):
        return None
    return row


@cache_control(no_cache=True)
def StatusView(request, pk):
    from zunzun.models import LRPStatus

    row = _load_owned_status_row(request, pk)
    if row is None:
        raise Http404

    # Completion handoff: redirect owner to the shareable ResultsView URL.
    # ResultsView serves the result HTML by token — no cookie check, so the
    # link is bookmarkable. Do NOT clear redirect_to_results here; ResultsView
    # reads it directly and is idempotent (reloading the shareable URL works).
    if row.state == LRPStatus.State.TERMINAL and row.redirect_to_results:
        return HttpResponseRedirect(f"/Results/{row.result_token}/")

    # Backstop: a child that died without finalizing its row (SIGKILL / OOM /
    # crash, or a failed terminal write) is detected here and promoted to
    # terminal so the request takes the completed branch below instead of
    # falling through to the in-progress render forever.
    _finalize_row_if_child_dead(row)

    # Terminal without a deliverable redirect: the fit finished (state ==
    # TERMINAL is the durable terminal signal) but there is nothing to serve — a
    # mid-fit crash whose error page could not be written. redirect_to_results is
    # never cleared (ResultsView reads it idempotently), so an empty redirect here
    # means no success redirect was ever written. Serve a terminal page so the poll
    # loop ends; without this the request falls through to the in-progress render
    # and StatusUpdateView (also keyed on state) bounces the browser back here
    # indefinitely.
    if row.state == LRPStatus.State.TERMINAL:
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
            "pk": pk,
        },
    )


@cache_control(no_cache=True)
def StatusUpdateView(request, pk):
    """JSON polling endpoint for the status page.

    Returns the live status fields (currentStatus, elapsed, loadavg) as JSON.
    On completion, returns {"completed": True}. redirect_to_results is never
    cleared — ResultsView reads it idempotently so the shareable link stays
    valid across refreshes.
    """
    from zunzun.models import LRPStatus

    row = _load_owned_status_row(request, pk)
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

    # Completion: report immediately. The durable terminal signal
    # (state == TERMINAL) — every terminal path (success, abort, mid-fit crash)
    # sets it. Keying off it (not the redirect alone) means a fit that finished
    # without a deliverable redirect — a crash whose error page could not be
    # linked — still ends the poll instead of heartbeating forever.
    # redirect_to_results is NOT cleared here; ResultsView reads it idempotently
    # so the shareable result link stays valid across refreshes.
    if row.state == LRPStatus.State.TERMINAL or row.redirect_to_results:
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
def StatusRedirectView(request):
    """Back-compat for the bare /StatusAndResults/ URL (the post-dispatch
    redirect target). Sends the browser to this session's newest owned
    in-progress row, else an 'expired' page."""
    from zunzun.models import LRPStatus

    # A keyless client has no session and therefore owns no rows; querying
    # owner_session_key="" would match any row created with an empty key.
    if not request.session.session_key:
        return render(
            request,
            "zunzun/generic_error.html",
            {"error": "No fit in progress for your session."},
        )
    row = (
        LRPStatus.objects.filter(owner_session_key=request.session.session_key)
        .exclude(state=LRPStatus.State.TERMINAL)
        .order_by("-pk")
        .first()
    )
    if row is None:
        return render(
            request,
            "zunzun/generic_error.html",
            {"error": "No fit in progress for your session."},
        )
    return HttpResponseRedirect(f"/StatusAndResults/{row.pk}/")


@cache_control(no_cache=True)
def ResultsView(request, token):
    """Serve the finished result HTML for a shareable capability token. No
    cookie check — possession of the token grants access. Aged-out token or
    missing result file renders a clean 'expired' page."""
    # django.conf.settings (not the raw `settings` module the rest of this file
    # uses) so the pytest-django `settings` fixture / override_settings can patch
    # TEMP_FILES_DIR in tests.
    from django.conf import settings as conf_settings

    from zunzun.models import LRPStatus

    row = LRPStatus.objects.filter(result_token=token).first()
    if row is None or not row.redirect_to_results:
        return render(
            request,
            "zunzun/generic_error.html",
            {"error": "This result has expired or is not yet ready."},
        )
    target = row.redirect_to_results
    if target.startswith(conf_settings.TEMP_FILES_DIR):
        try:
            with open(target, "r", encoding="utf-8") as f:
                return HttpResponse(f.read())
        except FileNotFoundError:
            return render(
                request,
                "zunzun/generic_error.html",
                {"error": "This result has expired."},
            )
        except OSError:
            _logger.exception("Failed to read result artifact %s", target)
            return render(
                request,
                "zunzun/generic_error.html",
                {"error": "This result could not be loaded. Please try running the fit again."},
            )
    return HttpResponseRedirect(target)


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
        # Capture the ranking dispatch's pk BEFORE it is overwritten by the
        # `request.session["lrp_status_pk"] = status_row.pk` assignment near
        # `LRPStatus.objects.create` below. At this point the session pointer
        # still refers to the FunctionFinder ranking run that produced the
        # results list. `TransferFormDataToDataObject` (called below) calls
        # LoadItemFromSessionStore, which FunctionFinderResults overrides to
        # read from ranking_status_pk rather than its own (empty) row.
        # Read the STABLE ranking-dispatch key so this value is not clobbered
        # when the results-page dispatch below writes its own (data-less) row pk
        # into lrp_status_pk. Every subsequent "Next/Previous Set" and "fit this
        # equation" link must read from the same ranking dispatch.
        LRP.ranking_status_pk = request.session.get("functionfinder_ranking_pk")

    else:
        return HttpResponse("I could not understand the web request.")

    #####################################################################
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    #####################################################################

    LRP.inEquationName = urllib.parse.unquote(inEquationName)
    LRP.inEquationFamilyName = urllib.parse.unquote(inEquationFamilyName)
    LRP.dimensionality = int(inDimensionality)

    if request.method == "POST":
        session_key = request.session.session_key or ""
        ip = request.META.get("REMOTE_ADDR", "")
        try:
            max_session = getattr(settings, "MAX_CONCURRENT_FITS_PER_SESSION", 1)
            max_ip = getattr(settings, "MAX_CONCURRENT_FITS_PER_IP", 4)
            per_session, per_ip = _active_fit_counts(session_key, ip)
            if per_session >= max_session or per_ip >= max_ip:
                # Probe-on-demand: only when a cap WOULD block, release any
                # provably-dead rows (crashed child whose heartbeat is still
                # fresh) and recount. Keeps the common under-cap path probe-free.
                from zunzun.models import LRPStatus

                fresh = time.time() - _HEARTBEAT_STALE_SECS
                candidates = (
                    LRPStatus.objects.exclude(state=LRPStatus.State.TERMINAL)
                    .filter(last_status_check__gte=fresh)
                    .filter(Q(owner_session_key=session_key) | Q(owner_ip=ip))
                )
                for r in candidates:
                    _finalize_row_if_child_dead(r)
                per_session, per_ip = _active_fit_counts(session_key, ip)
            if per_session >= max_session:
                return HttpResponse(
                    "You already have a fit in progress for your session. "
                    "Please wait for it to finish, or "
                    "<a href='/StatusAndResults/'>view its status</a>."
                )
            if per_ip >= max_ip:
                return HttpResponse(
                    "Too many fits are in progress from your network. "
                    "Please wait a moment and try again."
                )
        except OperationalError, InterfaceError:
            # Transient DB contention: fail OPEN (caps are anti-abuse, not a
            # correctness invariant) and warn via the named logger so a
            # persistent transient fault is still visible.
            _logger.warning(
                "Concurrency gate hit a transient DB error; allowing the fit",
                exc_info=True,
            )
        except Exception:
            # A non-transient error here is a real bug; do NOT silently run the
            # site uncapped forever — surface it loudly.
            _logger.exception("Concurrency gate failed with a non-transient error")
            raise

    # if this is not a POST, send an interface if needed
    if LRP.userInterfaceRequired:
        if request.method != "POST":
            request.session["cookie_test"] = 1
            # The interface form pre-populates from a prior dispatch's stored
            # data. On a GET no new dispatch row exists yet, so point
            # status_row_pk at that prior dispatch so
            # CreateUnboundInterfaceForm's LoadItemFromSessionStore reads resolve.
            # This is render-only (no status/data writes happen on the GET path);
            # the POST path creates and uses its own fresh row.
            if "RANK" in request.GET:
                # FunctionFinder "fit this equation" form: read the ranked list +
                # dataset from the STABLE ranking dispatch, not lrp_status_pk (a
                # FunctionFinderResults page render already moved that pointer to
                # its own data-less row).
                LRP.status_row_pk = request.session.get("functionfinder_ranking_pk")
            else:
                # Normal fit-form pre-fill: the session's most-recent dispatch.
                LRP.status_row_pk = request.session.get("lrp_status_pk")
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

    # Per-dispatch status row. Every dispatch creates an independent row; the
    # prior row is left for the housekeeping age-sweep (retention sweep) to
    # reclaim. The session pointer below moves to the new row.
    from zunzun.models import LRPDispatchData, LRPStatus

    # Stamp last_status_check at dispatch (not only at the first poll) so the
    # per-user gate's active check — state != TERMINAL AND last_status_check
    # within 300s — holds for 300s even if the client never polls (closed tab /
    # script). Without this, last_status_check would stay 0.0 until
    # StatusUpdateView's first heartbeat, and a non-polling client could bypass
    # the cap immediately. Restores the old
    # SetInitialStatusDataIntoSessionVariables semantics where dispatch time
    # doubled as the first heartbeat.
    if request.session.session_key is None:
        save_with_retry(request.session)  # mint a key before stamping ownership
    now = time.time()
    status_row = LRPStatus.objects.create(
        start_time=now,
        last_status_check=now,
        current_status="Initializing",
        owner_session_key=request.session.session_key,
        owner_ip=request.META.get("REMOTE_ADDR", ""),
    )
    request.session["lrp_status_pk"] = status_row.pk
    LRP.status_row_pk = status_row.pk

    # The FunctionFinder RANKING dispatch's data (ranked equation list + dataset)
    # is read back by every later FunctionFinderResults page and by the
    # "/FitEquation/?RANK=N" equation-fit form. Those follow-up dispatches each
    # OVERWRITE lrp_status_pk with their own (data-less) row, so the ranking pk
    # must live in a dedicated session key they do not clobber. Set it ONLY for
    # the ranking dispatch (the FunctionFinder__ path — NOT FunctionFinderResults).
    if request.path.find("FunctionFinder__") != -1:
        request.session["functionfinder_ranking_pk"] = status_row.pk

    # Create the per-dispatch data row in the PARENT, before the child spawns
    # and before SetInitialStatusDataIntoSessionVariables runs: save_items /
    # load_item assume it already exists, and pre-creating it here avoids a
    # get_or_create OneToOne create-race (an IntegrityError _retry won't catch).
    LRPDispatchData.objects.create(status=status_row)

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
    return HttpResponseRedirect(
        "http://" + request.META["HTTP_HOST"] + f"/StatusAndResults/{status_row.pk}/"
    )


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
