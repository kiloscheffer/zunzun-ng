import logging
import multiprocessing
import os
import time
import urllib.parse

import numpy
import pyeq3
from django import db
from django.core.mail import EmailMessage
from django.db import InterfaceError, OperationalError, close_old_connections
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control, cache_page
from django_ratelimit.decorators import ratelimit
from pyeq3.UdfSafety import UnsafeUDFError

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
    than SESSION_COOKIE_AGE). EXCLUDES completed rows that carry their own
    disk-bounded retention, so they outlive session expiry as documented:

      - FILE-BACKED results (state=TERMINAL, redirect_to_results under
        TEMP_FILES_DIR): retained by _sweep_orphaned_terminal_rows, reaped when
        the size-bounded prune removes the file.
      - FunctionFinder RANKING rows (state=TERMINAL, redirect_to_results a
        /FunctionFinderResults/ URL, not a file): retained by
        _sweep_orphaned_terminal_rows via their ffanchor marker, reaped when the
        size-prune removes that marker.

    Abandoned in-progress rows and crashed empty-redirect rows are still
    age-reaped. (Chained .exclude() calls keep a row matching EITHER clause.)

    SAFETY NET: FunctionFinder ranking rows are excluded from the size-based
    reap above because their retention is anchored by a temp/ffanchor marker —
    but that marker is a few bytes while the ranking's real cost (the ranked
    list + dataset) lives in LRPDispatchData, a DB row NOT counted toward
    MAX_TEMP_DIR_SIZE_IN_MBYTES. So an FF-heavy / low-artifact workload could
    keep temp/ under quota forever, never trip the prune that evicts the marker,
    and grow ranking rows + DB payloads without bound. A second reap applies a
    hard age ceiling (FF_RANKING_MAX_AGE, default 90d, >> SESSION_COOKIE_AGE) to
    FF ranking rows regardless of the marker, bounding that growth."""
    from django.conf import settings

    from zunzun.models import LRPStatus

    cutoff = time.time() - settings.SESSION_COOKIE_AGE
    LRPStatus.objects.filter(last_status_check__lt=cutoff, start_time__lt=cutoff).exclude(
        state=LRPStatus.State.TERMINAL,
        redirect_to_results__startswith=settings.TEMP_FILES_DIR,
    ).exclude(
        state=LRPStatus.State.TERMINAL,
        redirect_to_results__contains="/FunctionFinderResults/",
    ).delete()

    ff_cutoff = time.time() - settings.FF_RANKING_MAX_AGE
    LRPStatus.objects.filter(
        state=LRPStatus.State.TERMINAL,
        redirect_to_results__contains="/FunctionFinderResults/",
        last_status_check__lt=ff_cutoff,
        start_time__lt=ff_cutoff,
    ).delete()


def _sweep_orphaned_terminal_rows():
    """Delete TERMINAL LRPStatus rows whose disk-bounded retention artifact is
    gone from temp/ (the cascade also drops their LRPDispatchData):

      - FILE-BACKED results: reaped when their redirect_to_results file (under
        TEMP_FILES_DIR) is removed by the size-bounded prune.
      - FunctionFinder RANKING rows (file-less, redirect a /FunctionFinderResults/
        URL): reaped when their ffanchor_<pk> marker is removed by the prune.

    Both clocks are bounded by MAX_TEMP_DIR_SIZE_IN_MBYTES, so a shareable
    result and its row age out together. Empty-redirect rows are left to the
    age-sweep.
    """
    from django.conf import settings

    from zunzun.LongRunningProcess._unique import ff_anchor_path
    from zunzun.models import LRPStatus

    temp_dir = settings.TEMP_FILES_DIR
    for row in LRPStatus.objects.filter(state=LRPStatus.State.TERMINAL).only(
        "id", "redirect_to_results"
    ):
        target = row.redirect_to_results
        if not target:
            continue
        if target.startswith(temp_dir):
            if not os.path.exists(target):
                row.delete()
        elif "/FunctionFinderResults/" in target:  # FF ranking: file-less, anchor-tracked
            if not os.path.exists(ff_anchor_path(row.id)):
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

    # Reclaim LRPStatus rows whose user session has expired. Rows that carry
    # their own disk-bounded retention are excluded — file-backed TERMINAL
    # results AND FunctionFinder ranking rows (file-less /FunctionFinderResults/
    # redirects). Both are reclaimed by _sweep_orphaned_terminal_rows instead
    # (tied to the temp/ result file / ffanchor marker), so shareable
    # /Results/<token>/ links survive past session expiry.
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
    # disk-bounded retention artifact was removed by the temp-dir prune above:
    # file-backed results whose result file is gone, AND FunctionFinder ranking
    # rows whose ffanchor_<pk> marker is gone. Runs after the prune so
    # newly-trimmed files/markers are swept in the same housekeeping pass. Only
    # empty-redirect (e.g. crashed) rows are left to the row age-sweep.
    try:
        _sweep_orphaned_terminal_rows()
    except Exception:
        logging.exception("Housekeeping: orphaned-terminal-rows sweep failed")


@cache_control(no_cache=True)
@ratelimit(key="ip", rate="12/m", block=False)
@middleware.rate_limit_sleep
def EvaluateAtAPointView(request, token):
    import sys

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
    if LRP.dimensionality not in (2, 3):
        # dimensionality is written server-side from the URL path integer, so
        # anything else means a corrupt/tampered dispatch row. Reject it here,
        # before it can steer the equation lookup below (which treats any
        # non-2 value as 3D).
        return HttpResponse("This result has expired.")
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
        # The live scipy spline object isn't saved (it's not JSON-serializable)
        # — see FitSpline.SaveSpecificDataToSessionStore. solvedCoefficients IS
        # the tck tuple, and pyeq3's Spline models rebuild the callable spline
        # from it on demand (Models_*D/Spline.BuildSplineFromSolvedCoefficients,
        # invoked by the CalculateModelPredictions call below). So we only supply
        # inputs here: solvedCoefficients is assigned further down; 3D additionally
        # needs the degrees, which scipy's BivariateSpline.tck does NOT carry
        # (FitSpline persists them under splineDegrees) — hand them to
        # xOrder/yOrder, where the rebuild reads them. 2D needs nothing extra
        # (UnivariateSpline._eval_args bundles the degree at index 2).
        if LRP.dimensionality == 3:
            splineDegrees = LRP.LoadItemFromSessionStore("data", "splineDegrees")
            if not splineDegrees:
                # A 3D-spline result saved before splineDegrees was persisted
                # (a pre-fix dispatch row) can't be reconstructed — fail
                # gracefully instead of unpacking None into a 500.
                return HttpResponse("This result has expired.")
            equation.xOrder, equation.yOrder = splineDegrees
    elif equation.userDefinedFunctionFlag:
        equation.userDefinedFunctionText = LRP.LoadItemFromSessionStore(
            "data", "udfEditor_" + str(equation.GetDimensionality()) + "D"
        )
        # pyeq3 validates the UDF against its AST allow-list inside
        # ParseAndCompileUserFunctionString before compiling, so a tampered
        # dispatch row carrying a malicious UDF can never reach the eval inside
        # CalculateModelPredictions below. The form gate already rejects these in
        # normal flow; this is the same gate on the rehydration path.
        try:
            equation.ParseAndCompileUserFunctionString(
                equation.userDefinedFunctionText, LRP.dimensionality
            )
        except UnsafeUDFError:
            return HttpResponse("Invalid data submitted, please try again.")
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
    # For splines, solvedCoefficients IS the tck tuple — pyeq3's Spline
    # BuildSplineFromSolvedCoefficients consumes it (coercing each part with
    # numpy.asarray) and its CalculateModelPredictions ignores inCoeffs, so
    # leave it as a list.
    raw_coeffs = LRP.LoadItemFromSessionStore("data", "solvedCoefficients")
    if equation.splineFlag:
        equation.solvedCoefficients = raw_coeffs
    else:
        equation.solvedCoefficients = numpy.array(raw_coeffs)

    # make bound Django form and call form.is_valid()
    # (dimensionality is validated to {2, 3} right after it is loaded, above)
    if LRP.dimensionality == 2:
        evaluationForm = forms.EvaluateAtAPointForm_2D(request.POST)
    else:
        evaluationForm = forms.EvaluateAtAPointForm_3D(request.POST)

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


def _reservation_exceeds_cap(status_pk, session_key, ip, max_session, max_ip):
    """After creating our LRPStatus row, decide if WE are an excess creator
    that raced past the (check-then-act) gate.  Counts active (non-TERMINAL,
    fresh-heartbeat) rows created no later than ours (pk <= status_pk) for this
    session / IP; if that exceeds the cap we lost the race (the earliest `cap`
    rows always survive — deterministic, no over-rejection, single dispatch
    always counts 1).  Empty session_key / ip never reserve a slot."""
    from zunzun.models import LRPStatus

    fresh = time.time() - _HEARTBEAT_STALE_SECS
    base = LRPStatus.objects.exclude(state=LRPStatus.State.TERMINAL).filter(
        last_status_check__gte=fresh, pk__lte=status_pk
    )
    if session_key and base.filter(owner_session_key=session_key).count() > max_session:
        return True
    if ip and base.filter(owner_ip=ip).count() > max_ip:
        return True
    return False


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


def _ranking_pk_from_token(token):
    """pk of the FunctionFinder ranking LRPStatus row addressed by a capability
    token, or None if the token is empty/unknown (aged-out or invalid). Session-
    independent by construction: this is what lets a shared /FunctionFinderResults/
    link resolve in any browser session, and what stops two concurrent rankings
    from sharing one mutable session slot."""
    from zunzun.models import LRPStatus

    if not token:
        return None
    row = LRPStatus.objects.filter(result_token=token).only("id").first()
    return row.pk if row else None


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
    # Forward/legacy compat: a FunctionFinder ranking's redirect_to_results is a
    # /FunctionFinderResults/ URL the token-resolved dispatch needs to carry
    # &ranking=<token>. Rows written before token-binding (pre-deploy, still
    # retained) lack it; append this row's own token (== the URL token) so recent
    # completed FunctionFinder results survive the cutover instead of reading as
    # expired. Idempotent: new rows already include &ranking=, so this is a no-op.
    if "/FunctionFinderResults/" in target and "ranking=" not in target:
        target = target + "&ranking=" + token
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

    # Demo-mode hourly fit cap (per IP). Demo-gated, so provably inert on a
    # normal deployment. Sits ABOVE the LRP dispatch and the concurrency gate:
    # one POST here == one "run", and the run that exceeds the hourly ceiling is
    # refused before any work. `settings` is the module-level root import
    # (views.py:19); `render` is imported at module top. Reuses the same
    # ratelimit cache as the existing 12/m limiter.
    if settings.DEMO_MODE and request.method == "POST":
        from django_ratelimit.core import is_ratelimited

        if is_ratelimited(
            request,
            group="demo_fits",
            key="ip",
            rate=f"{settings.DEMO_MAX_FITS_PER_HOUR}/h",
            method=["POST"],
            increment=True,
        ):
            return render(
                request,
                "zunzun/demo_limit_reached.html",
                {
                    "header_text": "ZunZunNG",
                    "subtitle_text": "Online Curve Fitting and Surface Fitting",
                    "demo_max_fits_per_hour": settings.DEMO_MAX_FITS_PER_HOUR,
                },
                status=429,
            )

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
        # Resolve the ranking dispatch by the capability token in the URL
        # (?ranking=<token>). This is session-independent: any recipient with
        # the URL can view the results regardless of which session did the
        # original ranking. A missing/invalid token (aged-out or wrong URL)
        # short-circuits with a clean expired message rather than crashing.
        token = request.GET.get("ranking", "")
        ranking_pk = _ranking_pk_from_token(token)
        if ranking_pk is None:
            return render(
                request,
                "zunzun/generic_error.html",
                {"error": "This result has expired or is not yet ready."},
            )
        LRP.data_source_pk = ranking_pk
        LRP.ranking_token = token
        # Capability token in the URL is the identity — admit a cold (cookieless)
        # recipient through the cookie_test gate below, mirroring HomePageView.
        request.session["cookie_test"] = 1

    else:
        return HttpResponse("I could not understand the web request.")

    #####################################################################
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    #####################################################################

    LRP.inEquationName = urllib.parse.unquote(inEquationName)
    LRP.inEquationFamilyName = urllib.parse.unquote(inEquationFamilyName)
    LRP.dimensionality = int(inDimensionality)

    # Hoist ownership/cap values unconditionally so they are in scope at the
    # post-create reservation re-check (FIX #3) further below.
    session_key = request.session.session_key or ""
    ip = request.META.get("REMOTE_ADDR", "")
    max_session = getattr(settings, "MAX_CONCURRENT_FITS_PER_SESSION", 1)
    max_ip = getattr(settings, "MAX_CONCURRENT_FITS_PER_IP", 4)

    # FunctionFinderResults is a GET that also reaches the status-row-creation
    # + spawn path (userInterfaceRequired=False, not gated by the POST check).
    # Include it so refresh/Next-spam cannot spawn unbounded render children.
    _will_spawn_child = request.method == "POST" or (
        request.path.find("FunctionFinderResults/") != -1
    )

    if _will_spawn_child:
        try:
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
            # data. On a GET no new dispatch row exists yet, so set
            # data_source_pk (the read source) to that prior dispatch so
            # CreateUnboundInterfaceForm's LoadItemFromSessionStore reads
            # resolve via _data_read_pk(). This is render-only (no status/data
            # writes happen on the GET path); the POST path creates and uses
            # its own fresh row, and status_row_pk stays unset here.
            if "RANK" in request.GET:
                # The ranking identity rides in the URL (&ranking=<token>), not a
                # session slot, so the pre-fill resolves cross-session.
                ranking_pk = _ranking_pk_from_token(request.GET.get("ranking"))
                if ranking_pk is None:
                    # Tokenless/aged-out RANK link — e.g. a "Go to this equation"
                    # link baked into a FunctionFinderResults page rendered before
                    # token-binding (those links lack &ranking=), now served
                    # verbatim from temp/. Show a clear, actionable expiry message
                    # (parity with the FunctionFinderResults Prev/Next short-circuit)
                    # instead of falling through to the opaque "error building the
                    # form" path below. Pre-deploy result FILES cannot be link-
                    # rewritten on serve (the ranking token is not persisted on the
                    # served results-page row), so this is the graceful degradation
                    # for that transient cutover window.
                    return render(
                        request,
                        "zunzun/generic_error.html",
                        {
                            "error": "This result has expired or is not yet ready. "
                            "Please run the function finder again."
                        },
                    )
                # Read source for the render-only pre-fill: the ranking row.
                # Leave status_row_pk unset (no dispatch row exists on a GET);
                # the base LoadItemFromSessionStore reads via _data_read_pk().
                LRP.data_source_pk = ranking_pk
            else:
                # Normal fit-form pre-fill: read the session's most-recent
                # dispatch data via data_source_pk (read source), not the
                # write-target status_row_pk.
                LRP.data_source_pk = request.session.get("lrp_status_pk")
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

    # Post-create race guard (FIX #3): close the check-then-act window.  Two
    # near-simultaneous dispatches (double-click) can both pass the pre-create
    # gate above.  Now that our row exists (with a real pk), recount with
    # pk <= status_row.pk so the earliest `cap` creators always win and the
    # later excess creator is the one that backs off.  At this point only the
    # LRPStatus row exists; LRPDispatchData + child spawn happen below, so
    # status_row.delete() is the only cleanup needed.
    if _will_spawn_child and _reservation_exceeds_cap(
        status_row.pk, session_key, ip, max_session, max_ip
    ):
        status_row.delete()
        return HttpResponse(
            "You already have a fit in progress for your session. "
            "Please wait for it to finish, or "
            "<a href='/StatusAndResults/'>view its status</a>."
        )

    request.session["lrp_status_pk"] = status_row.pk
    LRP.status_row_pk = status_row.pk
    LRP.result_token = status_row.result_token

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

    # Host-relative redirect: never build the Location from the client-supplied
    # Host header (ALLOWED_HOSTS = ["*"] makes it attacker-controlled), and let
    # the browser keep the request scheme so an https request behind a TLS-
    # terminating proxy isn't downgraded to http://.
    return HttpResponseRedirect(f"/StatusAndResults/{status_row.pk}/")


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
    # Load average is intentionally NOT rendered here: this page is
    # @cache_page-cached for an hour, so a baked-in snapshot would freeze.
    # The Server Load panel fetches live values from ServerLoadView via
    # ServerLoadPoll.js instead. coreCount IS rendered (it feeds the panel's
    # explanation): it's a machine constant, so caching it is harmless.
    items_to_render["coreCount"] = multiprocessing.cpu_count()

    return render(request, "zunzun/home_page.html", items_to_render)


@cache_control(no_cache=True)
def ServerLoadView(request):
    """Live 1/5/15-minute load average as JSON for the home page panel.

    The home page is @cache_page-cached for 60 minutes, which would freeze
    any load-average value rendered into its HTML. This no-cache companion
    endpoint is polled by ServerLoadPoll.js so the Server Load panel shows
    current values. Not rate-limited, mirroring StatusUpdateView (the other
    short-interval JS poll target).
    """
    return JsonResponse({"loadavg": list(platform_compat.get_loadavg())})


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
