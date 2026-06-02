"""Cross-platform end-to-end smoke test for zunzun-ng.

Starts a Waitress subprocess on a free port, runs the scenarios below
against it, then stops the server. Exits 0 iff all scenarios pass.

Scenarios
---------

1. **polynomial_quadratic_2D** — direct 2D polynomial-quadratic fit.
2. **evaluate_at_a_point** — chained after scenario 1; POSTs X=7.0
   against the session's solved coefficients.
3. **function_finder_2D** — ranks an Exponential-only search.
4. **function_finder_detail_2D** — fits the RANK=1 equation.
4b. **function_finder_cross_session_2D** — a fresh session (no cookies)
    renders the ranking's results via the &ranking=<token> URL.
5. **characterize_2D** — descriptive statistics only, no fit.
6. **characterize_3D** — 3D characterize with animationSize enabled;
   verifies the ScatterAnimation GIF loads with ≥2 frames.
7. **polynomial_quadratic_3D** — 3D full-quadratic fit with animation
   enabled; verifies the SurfaceAnimation GIF loads with ≥2 frames.
8. **all_equations_2D** — GET AllEquations listing.
9. **invalid_form_post** — malformed data → error template.
10. **spline_2D** — 2D cubic spline fit with smoothness=1.0, chained into
    an `/EvaluateAtAPoint/` POST to verify the serializer-coerced
    `scipySpline` tck round-trips through the session.
11. **udf_2D** — 2D User Defined Function fit with formula `a + b*X`,
    chained into an `/EvaluateAtAPoint/` POST to verify
    `solvedCoefficients` round-trips through the session.
12. **concurrent_2D** — two 2D polynomial-quadratic fits dispatched in the
    same browser session (session cap raised to 2 via env var), polled
    independently by pk, each evaluated at X=7.0.  Asserts distinct pks,
    distinct tokens, distinct evaluations (the clobber-bug regression), and
    shareability of both result URLs from a fresh session (no cookies).

Usage:
  uv run python scripts/smoke_test.py
"""

import contextlib
import glob
import re
import socket
import subprocess
import sys
import time

import requests


def _find_free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# 10-point dataset used by the direct polynomial-quadratic fit scenario
# (matches funkload_tests/test_Simple.py default_data2D).
_DATA_2D_POLY = """X Y
5.357 3.76
5.684 6.1
6.097 4.94
6.241 7.104
6.697 2.054
7.061 1.65
7.457 0.412
8.236 2.016
8.531 3.8
9.861 1.95
"""

# Second 2D dataset for the concurrent_2D scenario.  Same X column as
# _DATA_2D_POLY but all Y values shifted by +5, so the fitted quadratic
# coefficients are meaningfully different.  Used to prove that
# /EvaluateAtAPoint/<tokenA>/ and /EvaluateAtAPoint/<tokenB>/ return
# DIFFERENT predictions — the clobber-bug regression test.
_DATA_2D_POLY_B = """X Y
5.357 8.76
5.684 11.1
6.097 9.94
6.241 12.104
6.697 7.054
7.061 6.65
7.457 5.412
8.236 7.016
8.531 8.8
9.861 6.95
"""

# Default FunctionFinder 2D dataset (matches DefaultData.defaultData2D).
# Monotonic increasing Y — a fittable shape that the Exponential family
# can score reasonably well against.
_DATA_2D_FF = """
5.357    0.376
5.457    0.489
5.797    0.874
5.936    1.049
6.161    1.327
6.697    2.054
6.731    2.077
6.775    2.138
8.442    4.744
9.769    7.068
9.861    7.104
"""

_POLY_QUAD_FIELDS = {
    "commaConversion": "I",
    "graphSize": "320x240",
    "animationSize": "0x0",
    "scientificNotationX": "AUTO",
    "scientificNotationY": "AUTO",
    "dataNameX": "X Data",
    "dataNameY": "Y Data",
    "graphScaleRadioButtonX": "0.050",
    "graphScaleRadioButtonY": "0.050",
    "logLinX": "LIN",
    "logLinY": "LIN",
    "logLinZ": "LIN",
    "fittingTarget": "SSQABS",
    "textDataEditor": _DATA_2D_POLY,
}

# Spline 2D form fields. Derived from _POLY_QUAD_FIELDS but without
# fittingTarget (FitSpline.SpecificEquationBoundInterfaceCode marks it
# required=False on bind), plus splineSmoothness and splineOrderX which
# FitSpline forces required=True. splineOrderX=3 needs at least 4 distinct
# X values, and _DATA_2D_POLY has 10.
_SPLINE_2D_FIELDS = {
    "commaConversion": "I",
    "graphSize": "320x240",
    "animationSize": "0x0",
    "scientificNotationX": "AUTO",
    "scientificNotationY": "AUTO",
    "dataNameX": "X Data",
    "dataNameY": "Y Data",
    "graphScaleRadioButtonX": "0.050",
    "graphScaleRadioButtonY": "0.050",
    "logLinX": "LIN",
    "logLinY": "LIN",
    "logLinZ": "LIN",
    "textDataEditor": _DATA_2D_POLY,
    "splineSmoothness": "1.0",
    "splineOrderX": "3",
}

# Spline output pages differ from polynomial pages: no covariance
# matrix (B-splines have knots/coefs, not parameter covariance in the
# Fisher-information sense), and the section heading is just "Fit
# Statistics" without the "Coefficient and" prefix. The spline-specific
# "Coefficients And Knot Points" dropdown is a strong signal that the
# spline report template rendered correctly end-to-end.
_SPLINE_EXPECTED_MARKERS = [
    "Fit Statistics",
    "Minimum:",
    "Maximum:",
    "Coefficients And Knot Points",
]

# UDF 2D form fields. Same base as _POLY_QUAD_FIELDS (UDF uses
# fittingTarget, unlike spline) plus the udfEditor text. "a + b*X" is the
# simplest non-trivial linear UDF — two coefficients, guaranteed to fit
# the 10-point polynomial dataset, and exercises the session
# userDefinedFunctionText round-trip + ParseAndCompileUserFunctionString.
_UDF_2D_FIELDS = dict(
    _POLY_QUAD_FIELDS,
    udfEditor="a + b*X",
)

# FunctionFinder fields. Only the Exponential family is enabled so the
# top-ranked equation is guaranteed nonlinear — this exercises pyeq3's
# differential-evolution initial-estimate path in the subsequent detail
# fit. smoothnessControl2D=2 keeps per-equation coefficient count small.
_FF_2D_FIELDS = {
    "commaConversion": "I",
    "dataNameX": "X Data",
    "dataNameY": "Y Data",
    "smoothnessControl2D": "2",
    "smoothnessExactOrMax": "M",
    "equationFamilyInclusion": ["Exponential"],
    "extendedEquationTypes": ["STANDARD"],
    "fittingTarget": "SSQABS",
    "logLinX": "LIN",
    "logLinY": "LIN",
    "logLinZ": "LIN",
    "textDataEditor": _DATA_2D_FF,
}

_POLY_EXPECTED_MARKERS = [
    "Coefficient and Fit Statistics",
    "Coefficient Covariance Matrix",
    "Minimum:",
    "Maximum:",
    # Dropdown section titles that only render when equationInstance is
    # truthy on the LRP (see FittingBaseClass.build_child_payload). These
    # catch regressions where parent-only state doesn't cross the spawn
    # payload boundary and the template falls back to its "no equation"
    # rendering.
    "Text Reports",
    "Scatterplots",
]

_FF_EXPECTED_MARKERS = [
    "Function Finder Results",
    "Model and Error Plots",
    "Rank 1",
]

# Larger FunctionFinder 2D scenario for the parallel-perf acceptance run.
# BioScience + Exponential STANDARD families with smoothnessControl=5
# typically yield ~80-200 nonlinear-fittable equations — enough work to
# meaningfully exercise the persistent FitPool's worker reuse across many
# task chunks. Used by the --scenario=function-finder-2D-large opt-in
# (default smoke runs the smaller _FF_2D_FIELDS scenario).
_FF_2D_LARGE_FIELDS = {
    "commaConversion": "I",
    "dataNameX": "X Data",
    "dataNameY": "Y Data",
    "smoothnessControl2D": "5",
    "smoothnessExactOrMax": "M",
    "equationFamilyInclusion": ["BioScience", "Exponential"],
    "extendedEquationTypes": ["STANDARD"],
    "fittingTarget": "SSQABS",
    "logLinX": "LIN",
    "logLinY": "LIN",
    "logLinZ": "LIN",
    "textDataEditor": _DATA_2D_FF,
}

_CHAR_2D_FIELDS = {
    "commaConversion": "I",
    "dataNameX": "X Data",
    "dataNameY": "Y Data",
    "textDataEditor": _DATA_2D_POLY,
    "graphSize": "320x240",
    "scientificNotationX": "AUTO",
    "scientificNotationY": "AUTO",
    "graphScaleRadioButtonX": "0.050",
    "graphScaleRadioButtonY": "0.050",
    "logLinX": "LIN",
    "logLinY": "LIN",
}

_CHAR_EXPECTED_MARKERS = [
    "Data Statistics",
    "Minimum:",
    "Maximum:",
    "Mean:",
    "Standard Deviation:",
]

# 3D dataset for the polynomial_quadratic_3D scenario. Uses
# non-overlapping X and Y ranges (X in {1,2,3,4}, Y in {5,6,7}) so the
# union of distinct independent values is 7 — larger than the 6
# coefficients of a 3D Full Quadratic (required by Equation_3D.clean()).
# Z follows z = X + 2*Y + small quadratic variation so the fit is
# well-posed.
_DATA_3D_POLY = """X Y Z
1.0 5.0 11.0
1.0 6.0 13.0
1.0 7.0 15.0
2.0 5.0 12.0
2.0 6.0 14.0
2.0 7.0 16.0
3.0 5.0 13.5
3.0 6.0 15.5
3.0 7.0 17.5
4.0 5.0 15.0
4.0 6.0 17.0
4.0 7.0 19.0
"""

_POLY_QUAD_3D_FIELDS = {
    "commaConversion": "I",
    "graphSize": "320x240",
    # animationSize=320x240 (not 0x0) exercises the ScatterAnimation and
    # SurfaceAnimation paths that use matplotlib.animation.PillowWriter.
    "animationSize": "320x240",
    "scientificNotationX": "AUTO",
    "scientificNotationY": "AUTO",
    "scientificNotationZ": "AUTO",
    "dataNameX": "X Data",
    "dataNameY": "Y Data",
    "dataNameZ": "Z Data",
    "graphScaleRadioButtonX": "0.050",
    "graphScaleRadioButtonY": "0.050",
    "graphScaleRadioButtonZ": "0.050",
    "logLinX": "LIN",
    "logLinY": "LIN",
    "logLinZ": "LIN",
    "fittingTarget": "SSQABS",
    "textDataEditor": _DATA_3D_POLY,
    "rotationAnglesAzimuth": "165",
    "rotationAnglesAltimuth": "20",
}

# CharacterizeData 3D + animation. Reuses the same 3D dataset as the fit
# scenario; distinct-values requirement doesn't apply to characterize.
_CHAR_3D_FIELDS = {
    "commaConversion": "I",
    "graphSize": "320x240",
    "animationSize": "320x240",
    "scientificNotationX": "AUTO",
    "scientificNotationY": "AUTO",
    "scientificNotationZ": "AUTO",
    "dataNameX": "X Data",
    "dataNameY": "Y Data",
    "dataNameZ": "Z Data",
    "graphScaleRadioButtonX": "0.050",
    "graphScaleRadioButtonY": "0.050",
    "graphScaleRadioButtonZ": "0.050",
    "logLinX": "LIN",
    "logLinY": "LIN",
    "logLinZ": "LIN",
    "textDataEditor": _DATA_3D_POLY,
    "rotationAnglesAzimuth": "165",
    "rotationAnglesAltimuth": "20",
}

_ALL_EQUATIONS_MARKERS = [
    # /AllEquations/2/Polynomial/ URL — the path-segment `Polynomial`
    # is the view's `inAllOrStandardOnly` flag, not a family filter.
    # The header is "ZunZunNG List Of All Standard 2D Equations"
    # and the page lists every family; "Polynomial" appears as a
    # section heading and in many equation links.
    "All Standard 2D Equations",
    "Polynomial",
]

_EVAL_AT_POINT_FIELDS = {
    "x": "7.0",  # EvaluateAtAPointForm_2D uses lowercase 'x'
}

# EvaluateAtAPointView returns plain HTML "evaluates to <b>{value}</b>"
# on success (see views.py:153). The "evaluates to" anchor is stable
# across pyeq3 output variants.
_EVAL_AT_POINT_MARKERS = [
    "evaluates to",
]

# Deliberately malformed data: Y column missing entirely, plus a
# non-numeric row. FittingBaseClass validation should reject and
# render invalid_form_data.html.
_INVALID_DATA = """X
not_a_number
5.357
6.097
"""

_INVALID_FIELDS = dict(_POLY_QUAD_FIELDS, textDataEditor=_INVALID_DATA)

# invalid_form_data.html / Equation_2D.clean() message fragments. The
# plan's "could not" string is not actually in the error template on
# this codebase; the shipped error is "No data points found..." under
# an "Error In Form" / "Form error :" heading.
_INVALID_MARKERS = [
    "Error In Form",
    "Form error",
]

# Pattern for the first /Equation/{dim}/{family}/{equation}/?RANK=1
# hyperlink in the FunctionFinder results listing. family and equation
# segments are URL-encoded (%20 for spaces, %28 for '(', etc.) and
# intentionally stay encoded — the fit POST URL reuses them verbatim.
_RANK1_LINK = re.compile(
    r"/Equation/(?P<dim>\d+)/(?P<family>[^/?\"<>]+)/(?P<equation>[^/?\"<>]+)/\?RANK=1"
)


def _check_animation_gif(session, base, body, name_prefix, min_frames=2):
    """Find a /temp/zun_*_{name_prefix}_*.gif href in body, read that file
    directly off disk, verify the bytes load as a GIF with ≥min_frames
    animated frames.

    Returns None on success, or an error string on failure.

    Used by the 3D scenarios to confirm matplotlib.animation.PillowWriter
    actually produced a multi-frame animated GIF. The name_prefix is the
    3-letter uniqueAnchorName — `san` (ScatterAnimation, for CharacterizeData
    output) or `sua` (SurfaceAnimation, for fit output) — set on GraphReport
    subclasses in zunzun/LongRunningProcess/ReportsAndGraphs.py. The anchor
    sits in the middle of the filename per the zun_<pid>_<ms>_<anchor>_<rank>
    scheme.

    Reads off disk (rather than via HTTP) because Django under Waitress
    with DEBUG=False does not serve STATIC_URL paths — that's nginx's
    job in production. The smoke runs on the same machine as the
    server, so reading `temp/{filename}` directly is both simpler and
    version-independent. `session` and `base` are unused but kept in
    the signature so future variants (fetching via HTTP on a remote
    staging server, say) can slot in without changing call sites.
    """
    del session, base  # intentionally unused for the on-disk form
    import os

    from PIL import Image

    # Filenames are zun_<pid>_<ms>_<anchor>_<rank>.gif; anchor sits in the middle.
    pattern = re.compile(r'/temp/(zun_[^"\']*_' + re.escape(name_prefix) + r'_[^"\']*\.gif)')
    match = pattern.search(body)
    if not match:
        return f"[{name_prefix}] no /temp/zun_*_{name_prefix}_*.gif href found in response body"
    filename = match.group(1)
    path = os.path.join("temp", filename)
    if not os.path.exists(path):
        return f"[{name_prefix}] {path} does not exist on disk"
    with Image.open(path) as img:
        if img.format != "GIF":
            return f"[{name_prefix}] {path} is not GIF (format={img.format!r})"
        if img.n_frames < min_frames:
            return f"[{name_prefix}] {path} has {img.n_frames} frames, expected >= {min_frames}"
    return None


def _wait_for_port(port: int, timeout_s: float = 30.0) -> bool:
    """Raw-socket readiness probe. Returns True if Waitress accepts a
    connection on `port` within the timeout, False otherwise.

    Using requests.get as a warmup probe would execute HomePageView,
    which is @cache_page-decorated; the cached response poisons session
    cookies for the real test session afterward. A raw TCP connect
    never touches Django so it leaves no server-side side effects.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with contextlib.closing(socket.create_connection(("127.0.0.1", port), timeout=1)):
                return True
        except OSError, ConnectionRefusedError:
            time.sleep(0.5)
    return False


def _dump_body(tag: str, body: str) -> str:
    """Write the body to temp/_smoke_last_body_{tag}.html for inspection."""
    path = f"temp/_smoke_last_body_{tag}.html"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
    except Exception:
        pass
    return path


def _check_markers(name: str, body: str, expected: list[str]) -> str | None:
    """Return an error string if any marker is missing, else None."""
    missing = [m for m in expected if m not in body]
    if not missing:
        return None
    path = _dump_body(name, body)
    preview = body[:2000]
    return (
        f"[{name}] missing markers: {missing}\n"
        f"full body written to {path} ({len(body)} chars)\n"
        f"--- preview (first 2000 chars) ---\n{preview}\n--- end ---"
    )


def _dispatch_and_poll_pk(
    session: requests.Session,
    base: str,
    name: str,
    post_url: str,
    form_fields: dict,
    timeout_s: float,
) -> tuple[str | None, str | None, str | None]:
    """POST to post_url, capture the dispatch pk from the 302 Location, then
    poll the PK-addressed /StatusAndResults/<pk>/ URL until the fit completes.

    Polls the PK URL (not the bare /StatusAndResults/ redirect): once the fit
    completes, its row goes TERMINAL and StatusRedirectView — which serves the
    bare URL — excludes TERMINAL rows, so the bare URL can never observe the
    finished result. Only StatusView (the pk URL) redirects a completed row
    through to its result (a /Results/<token>/ file page, or — for a
    URL-redirect result like FunctionFinder — onward to the generated results
    URL). With allow_redirects=True the polled body is that final page.

    This is the shared core for every fit scenario. Returns
    ``(error_or_None, final_body_or_None, status_url_or_None)``: the body is the
    completed page's HTML so callers can assert markers, extract links, or check
    animation GIFs; the status_url lets a caller re-follow to read the final
    ``.url`` (the /Results/<token>/ URL) for token extraction.
    """
    post_resp = session.post(post_url, data=form_fields, allow_redirects=True)
    pk = _extract_pk_from_redirect(post_resp, base)
    if pk is None:
        _dump_body(f"{name}_dispatch", post_resp.text)
        return f"[{name}] could not extract dispatch pk from POST redirect", None, None
    status_url = base + f"/StatusAndResults/{pk}/"
    body = _poll_until_done_pk(session, base, status_url, timeout_s)
    if body is None:
        return f"[{name}] did not complete within {int(timeout_s)}s", None, None
    return None, body, status_url


def _run_scenario_capturing_url(
    session: requests.Session,
    base: str,
    name: str,
    post_url: str,
    form_fields: dict,
    expected_markers: list[str],
    timeout_s: float,
) -> tuple[str | None, str | None]:
    """POST, poll the dispatched fit by pk until done, assert structural
    markers, AND return the FINAL result URL so a chained
    /EvaluateAtAPoint/<token>/ caller can pull the capability token out of it.

    Returns ``(error_or_None, final_url_or_None)``. On success the first item
    is None and the second is the completed response's ``.url`` (the
    ``/Results/<token>/`` URL after the redirect chain). On any failure the
    second item is None. The token-less ``_run_scenario`` wraps this for the
    callers that don't need the URL.
    """
    err, body, status_url = _dispatch_and_poll_pk(
        session, base, name, post_url, form_fields, timeout_s
    )
    if err or body is None or status_url is None:
        return err, None
    err = _check_markers(name, body, expected_markers)
    if err:
        return err, None
    # Re-request the (now terminal) status URL to capture the FINAL /Results/
    # URL: StatusView redirects the completed row to /Results/<token>/, and
    # requests records that as resp.url after following the chain.
    final = session.get(status_url, allow_redirects=True)
    return None, final.url


def _run_scenario(
    session: requests.Session,
    base: str,
    name: str,
    post_url: str,
    form_fields: dict,
    expected_markers: list[str],
    timeout_s: float,
) -> str | None:
    """POST to post_url, poll until done, assert structural markers.
    Returns None on success or an error string.
    """
    err, _ = _run_scenario_capturing_url(
        session, base, name, post_url, form_fields, expected_markers, timeout_s
    )
    return err


def _run_ff_detail_scenario(
    session: requests.Session,
    base: str,
    name: str,
    ff_ranking_body: str,
    timeout_s: float,
) -> str | None:
    """Click into the top-ranked equation from a FunctionFinder ranking
    page and run its detailed fit.

    `ff_ranking_body` is the HTML from the preceding function_finder_2D
    scenario. Extracts the RANK=1 /Equation/.../ link and POSTs a fit to
    the corresponding /FitEquation__F__/.../ URL with the same form
    fields the direct polynomial-quadratic scenario uses (both routes
    through FitOneEquation with Equation_2D form fields).
    """
    match = _RANK1_LINK.search(ff_ranking_body)
    if not match:
        _dump_body(f"{name}_parent", ff_ranking_body)
        return f"[{name}] could not find RANK=1 equation link in the ranking body"
    dim = match.group("dim")
    family = match.group("family")
    equation = match.group("equation")
    print(f"[{name}] top-ranked: /{family}/{equation}/ (dim={dim})")

    fit_url = f"{base}/FitEquation__F__/{dim}/{family}/{equation}/"
    # Replace the data field with the FF data so the detail fit runs
    # against the same points the ranking saw. Everything else matches
    # the polynomial scenario's Equation_2D form expectations.
    detail_fields = dict(_POLY_QUAD_FIELDS, textDataEditor=_DATA_2D_FF)
    err, body, _ = _dispatch_and_poll_pk(session, base, name, fit_url, detail_fields, timeout_s)
    if err or body is None:
        return err
    return _check_markers(name, body, _POLY_EXPECTED_MARKERS)


def _extract_ranking_token(body: str) -> str | None:
    """Extract the FunctionFinder ranking token from a results page's links."""
    m = re.search(r"[?&]ranking=([A-Za-z0-9_-]+)", body)
    return m.group(1) if m else None


def _run_ff_cross_session_scenario(
    base: str,
    name: str,
    ff_ranking_body: str,
    timeout_s: float,
) -> str | None:
    """Cross-session shareability of a FunctionFinder result (BACKLOG #2817).

    Takes the owner's rendered ranking page body, extracts the &ranking=<token>,
    then drives a FRESH session (no cookies, no cookie_test) through the
    FunctionFinderResults GET. The dispatcher must resolve the ranking by token
    and set cookie_test, so the fresh session renders the results rather than
    landing on 'session/result expired'.
    """
    token = _extract_ranking_token(ff_ranking_body)
    if token is None:
        _dump_body(f"{name}_parent", ff_ranking_body)
        return f"[{name}] no &ranking= token found in the ranking results body"

    fresh = requests.Session()
    ff_url = base + f"/FunctionFinderResults/2/?RANK=1&ranking={token}"
    r = fresh.get(ff_url, allow_redirects=True)
    body = _poll_until_done_pk(fresh, base, r.url, timeout_s)
    if body is None:
        return f"[{name}] cross-session results poll timed out"
    if "expired" in body.lower():
        _dump_body(name, body)
        return f"[{name}] fresh session saw an 'expired' page (cross-session sharing broken)"
    err = _check_markers(name, body, _FF_EXPECTED_MARKERS)
    if err:
        return err
    print(f"[{name}] cross-session FunctionFinder result OK (fresh session, token only)")
    return None


_STATUS_PK_RE = re.compile(r"/StatusAndResults/(\d+)/")


def _poll_until_done_pk(
    session: requests.Session, base: str, status_url: str, timeout_s: float
) -> str | None:
    """Poll a pk-addressed /StatusAndResults/<pk>/ URL until the fit completes,
    FOLLOWING multi-stage redirect chains to their final settled page.

    Polls a SPECIFIC pk URL (never the bare /StatusAndResults/ redirect, which
    StatusRedirectView can't serve once the row is TERMINAL) so concurrent fits
    can be tracked independently. The fit is in-progress while id="currentStatus"
    is present in the followed response body.

    Two completion shapes:

    * Single-stage (a normal fit): on completion StatusView redirects the pk URL
      to /Results/<token>/; requests follows it, the body lacks currentStatus,
      and that result HTML is returned.

    * Two-stage (FunctionFinder): the RANKING dispatch's completion redirects
      through /Results/<rankToken>/ → /FunctionFinderResults/2/?RANK=1, which is
      a SECOND long-running dispatch — it 302s to a NEW /StatusAndResults/<pk2>/.
      Re-GETting the original ranking pk would re-trigger that second dispatch on
      every poll (a fresh row each time, racing the session's lrp_status_pk
      pointer → "session has expired"). To avoid that, this poll watches the
      FINAL URL after redirects: when it settles on a DIFFERENT
      /StatusAndResults/<pk2>/ than the one currently being polled, it switches
      to polling pk2. The second dispatch then completes to its own
      /Results/<token2>/ page (the real FunctionFinder results), which is
      returned. Harmless for single-stage fits — their final URL is /Results/,
      never a new status pk, so the switch never fires.

    Returns the final settled body on success, or None on timeout.
    """
    deadline = time.time() + timeout_s
    current_url = status_url
    while time.time() < deadline:
        r = session.get(current_url, allow_redirects=True)
        body = r.text
        if 'id="currentStatus"' not in body:
            return body
        # Still working. If the chain has handed off to a NEW status pk (the
        # FunctionFinder two-stage case), follow it so the next poll tracks the
        # live dispatch rather than re-triggering the handoff from the old pk.
        m = _STATUS_PK_RE.search(r.url)
        if m:
            settled = f"{base}/StatusAndResults/{m.group(1)}/"
            if settled != current_url:
                current_url = settled
                continue  # poll the new pk immediately, no sleep
        time.sleep(3)
    return None


def _extract_pk_from_redirect(response: requests.Response, base: str) -> str | None:
    """Extract the dispatch pk from a POST-redirect response.

    LongRunningProcessView redirects to /StatusAndResults/<pk>/ on POST.
    requests follows the redirect by default but records the full history;
    the original 302 Location header contains the pk.  Returns the pk string,
    or None if the header is missing or malformed.
    """
    for resp in response.history:
        location = resp.headers.get("Location", "")
        m = re.search(r"/StatusAndResults/(\d+)/", location)
        if m:
            return m.group(1)
    # Fallback: check the final URL (requests may have followed to it).
    m = re.search(r"/StatusAndResults/(\d+)/", response.url)
    if m:
        return m.group(1)
    return None


def _extract_token_from_results_url(url: str) -> str | None:
    """Extract the capability token from a /Results/<token>/ URL."""
    m = re.search(r"/Results/([A-Za-z0-9_-]+)/", url)
    return m.group(1) if m else None


def _run_concurrent_2D_scenario(
    session: requests.Session,
    base: str,
    timeout_s: float,
) -> str | None:
    """Concurrent-fits isolation smoke scenario.

    Two 2D polynomial-quadratic fits are dispatched within the SAME browser
    session (session cap must be >=2 on the server).  Each fit uses different Y
    data so the solved coefficients — and therefore the /EvaluateAtAPoint/
    predictions — differ.  The scenario asserts:

    1. Two DISTINCT dispatch pks (separate rows were created).
    2. Both fits complete (status pages eventually redirect to /Results/).
    3. Two DISTINCT result tokens.
    4. Both /Results/<token>/ pages contain the expected result markers.
    5. /EvaluateAtAPoint/<tokenA>/ and /EvaluateAtAPoint/<tokenB>/ at the
       same X return DIFFERENT values — the clobber-bug regression test.
    6. A FRESH session (no cookies) can GET /Results/<tokenA>/ and
       /Results/<tokenB>/ → 200 + result markers (shareability).
    """
    name = "concurrent_2D"

    # Cookie warmup. The fit dispatch requires session["cookie_test"], which is
    # set by HomePageView — but HomePageView is @cache_page-decorated, so once
    # ANY prior request populated its cache, a later session's GET / returns the
    # CACHED response and never runs the view body that sets cookie_test (the
    # same poisoning _wait_for_port documents). A GET to a fit-interface URL is
    # @cache_control(no_cache=True) and unconditionally sets cookie_test before
    # rendering the form, so it warms the cookie reliably no matter where this
    # scenario runs in the sequence.
    interface_url = base + "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/"
    session.get(interface_url)

    # --- Dispatch fit A (original Y data) ---
    fields_a = dict(_POLY_QUAD_FIELDS)  # Y from _DATA_2D_POLY
    r_a = session.post(
        base + "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/",
        data=fields_a,
        allow_redirects=True,
    )
    pk_a = _extract_pk_from_redirect(r_a, base)
    if pk_a is None:
        _dump_body(f"{name}_dispatch_a", r_a.text)
        return f"[{name}] could not extract pkA from dispatch redirect"

    # --- Dispatch fit B (Y data shifted +5) ---
    fields_b = dict(_POLY_QUAD_FIELDS, textDataEditor=_DATA_2D_POLY_B)
    r_b = session.post(
        base + "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/",
        data=fields_b,
        allow_redirects=True,
    )
    pk_b = _extract_pk_from_redirect(r_b, base)
    if pk_b is None:
        _dump_body(f"{name}_dispatch_b", r_b.text)
        return f"[{name}] could not extract pkB from dispatch redirect"

    if pk_a == pk_b:
        return f"[{name}] pkA == pkB ({pk_a}): both dispatches got the same status row"

    print(f"[{name}] dispatched pkA={pk_a} pkB={pk_b}")

    # --- Poll fit A to completion ---
    status_url_a = base + f"/StatusAndResults/{pk_a}/"
    body_a = _poll_until_done_pk(session, base, status_url_a, timeout_s)
    if body_a is None:
        return f"[{name}] fitA (pk={pk_a}) did not complete within {int(timeout_s)}s"

    # --- Poll fit B to completion ---
    status_url_b = base + f"/StatusAndResults/{pk_b}/"
    body_b = _poll_until_done_pk(session, base, status_url_b, timeout_s)
    if body_b is None:
        return f"[{name}] fitB (pk={pk_b}) did not complete within {int(timeout_s)}s"

    # --- Extract result tokens from the final URLs (after redirect chain) ---
    # After polling, the session has followed all redirects; the last GET was
    # the /Results/<token>/ page.  We need the token to build the evaluate URL.
    # Re-request each status URL with allow_redirects=True and capture the
    # final URL.
    r_results_a = session.get(status_url_a, allow_redirects=True)
    token_a = _extract_token_from_results_url(r_results_a.url)
    if token_a is None:
        _dump_body(f"{name}_results_a", r_results_a.text)
        return f"[{name}] could not extract tokenA from results URL: {r_results_a.url!r}"

    r_results_b = session.get(status_url_b, allow_redirects=True)
    token_b = _extract_token_from_results_url(r_results_b.url)
    if token_b is None:
        _dump_body(f"{name}_results_b", r_results_b.text)
        return f"[{name}] could not extract tokenB from results URL: {r_results_b.url!r}"

    if token_a == token_b:
        return f"[{name}] tokenA == tokenB ({token_a}): distinct fits share the same token"

    print(f"[{name}] tokenA={token_a[:12]}… tokenB={token_b[:12]}…")

    # --- Assert both result pages have expected markers ---
    err = _check_markers(f"{name}_results_a", r_results_a.text, _POLY_EXPECTED_MARKERS)
    if err:
        return err
    err = _check_markers(f"{name}_results_b", r_results_b.text, _POLY_EXPECTED_MARKERS)
    if err:
        return err

    # --- Evaluate both fits at the same X point and assert DIFFERENT results ---
    # This is the clobber-bug regression: before per-dispatch isolation, both
    # evaluations would read the SAME shared data blob and return the SAME
    # (last-written) result.
    eval_fields = {"x": "7.0"}
    r_eval_a = session.post(
        base + f"/EvaluateAtAPoint/{token_a}/",
        data=eval_fields,
        allow_redirects=True,
    )
    err = _check_markers(f"{name}_eval_a", r_eval_a.text, _EVAL_AT_POINT_MARKERS)
    if err:
        return err

    r_eval_b = session.post(
        base + f"/EvaluateAtAPoint/{token_b}/",
        data=eval_fields,
        allow_redirects=True,
    )
    err = _check_markers(f"{name}_eval_b", r_eval_b.text, _EVAL_AT_POINT_MARKERS)
    if err:
        return err

    eval_text_a = r_eval_a.text
    eval_text_b = r_eval_b.text
    if eval_text_a == eval_text_b:
        return (
            f"[{name}] CLOBBER BUG DETECTED: both fits evaluate to the same value at x=7.0\n"
            f"  evalA={eval_text_a!r}\n"
            f"  evalB={eval_text_b!r}\n"
            "  The two fits used DIFFERENT data; their predictions MUST differ.\n"
            "  This is the per-dispatch isolation regression."
        )

    print(f"[{name}] evalA={eval_text_a[:60]!r}  evalB={eval_text_b[:60]!r}  (distinct — OK)")

    # --- Shareability: a fresh session (no cookies) can GET both result URLs ---
    fresh_session = requests.Session()
    r_share_a = fresh_session.get(base + f"/Results/{token_a}/", allow_redirects=True)
    if r_share_a.status_code != 200:
        return (
            f"[{name}] shareability: GET /Results/{token_a[:12]}…/ returned "
            f"{r_share_a.status_code} (expected 200)"
        )
    err = _check_markers(f"{name}_share_a", r_share_a.text, _POLY_EXPECTED_MARKERS)
    if err:
        return err

    r_share_b = fresh_session.get(base + f"/Results/{token_b}/", allow_redirects=True)
    if r_share_b.status_code != 200:
        return (
            f"[{name}] shareability: GET /Results/{token_b[:12]}…/ returned "
            f"{r_share_b.status_code} (expected 200)"
        )
    err = _check_markers(f"{name}_share_b", r_share_b.text, _POLY_EXPECTED_MARKERS)
    if err:
        return err

    print(f"[{name}] shareability OK (both result URLs accessible from fresh session)")
    return None  # success


def run_smoke(scenario: str = "default") -> int:
    port = _find_free_port()
    base = f"http://127.0.0.1:{port}"
    # Pass env vars so spawned fit children inherit the same overrides.
    # ZUNZUN_MAX_CONCURRENT_FITS_PER_SESSION=2 is needed for the concurrent_2D
    # scenario; the default (1) is preserved for all other scenarios.
    import os

    server_env = os.environ.copy()
    server_env["ZUNZUN_MAX_CONCURRENT_FITS_PER_SESSION"] = "2"
    proc = subprocess.Popen(
        ["waitress-serve", f"--listen=127.0.0.1:{port}", "wsgi:application"],
        env=server_env,
    )
    try:
        if not _wait_for_port(port):
            print("ERROR: server never became ready", file=sys.stderr)
            return 1

        session = requests.Session()
        session.get(base + "/")  # establish session cookie

        errors = []

        # Opt-in scenarios for the parallel-perf acceptance run. The
        # 'default' value runs the full historical smoke sequence (~14
        # scenarios) which already includes a smaller function_finder_2D
        # scenario. Specific scenarios run ONLY that scenario in isolation.
        if scenario == "function-finder-2D-large":
            try:
                print("[function-finder-2D-large] starting")
                t_start = time.time()
                err = _run_scenario(
                    session,
                    base,
                    "function-finder-2D-large",
                    base + "/FunctionFinder__F__/2/",
                    _FF_2D_LARGE_FIELDS,
                    _FF_EXPECTED_MARKERS,
                    timeout_s=900,
                )
                wall = time.time() - t_start
                if err:
                    errors.append(err)
                else:
                    print(f"[function-finder-2D-large] OK in {wall:.1f}s")
            except Exception as e:
                errors.append(f"[function-finder-2D-large] exception: {e!r}")

            # Skip the rest of the default sequence in this mode
            if errors:
                print("SMOKE FAILED:")
                for err in errors:
                    print(f"  {err}")
                return 1
            print("SMOKE OK: function-finder-2D-large scenario passed")
            return 0

        if scenario == "concurrent-2D":
            try:
                print("[concurrent_2D] starting")
                t_start = time.time()
                err = _run_concurrent_2D_scenario(session, base, timeout_s=600)
                wall = time.time() - t_start
                if err:
                    errors.append(err)
                else:
                    print(f"[concurrent_2D] OK in {wall:.1f}s")
            except Exception as e:
                errors.append(f"[concurrent_2D] exception: {e!r}")

            if errors:
                print("SMOKE FAILED:")
                for err in errors:
                    print(f"  {err}")
                return 1
            print("SMOKE OK: concurrent-2D scenario passed")
            return 0

        # Scenario 1: direct polynomial-quadratic fit
        err, result_url = _run_scenario_capturing_url(
            session,
            base,
            "polynomial_quadratic_2D",
            base + "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/",
            _POLY_QUAD_FIELDS,
            _POLY_EXPECTED_MARKERS,
            timeout_s=600,
        )
        if err:
            errors.append(err)
        else:
            print("[polynomial_quadratic_2D] OK")
            token = _extract_token_from_results_url(result_url or "")
            if token is None:
                errors.append(
                    f"[evaluate_at_a_point] could not extract token from results URL: "
                    f"{result_url!r}"
                )
            else:
                r = session.post(
                    base + f"/EvaluateAtAPoint/{token}/",
                    data=_EVAL_AT_POINT_FIELDS,
                    allow_redirects=True,
                )
                err = _check_markers("evaluate_at_a_point", r.text, _EVAL_AT_POINT_MARKERS)
                if err:
                    errors.append(err)
                else:
                    print("[evaluate_at_a_point] OK")

        # Scenario 2: FunctionFinder ranking. Capture the final body for scenario 3.
        # FunctionFinder's completion is a URL-REDIRECT result (not a /Results/
        # file): the pk poll → StatusView → /Results/<token>/ → ResultsView,
        # which for a URL-redirect result issues HttpResponseRedirect to the
        # generated /FunctionFinderResults/2/?RANK=1 URL. With allow_redirects
        # the final body IS the FunctionFinder ranking page, so we assert the FF
        # markers on it directly (no token / evaluate involved for FF).
        ff_anchors_before = set(glob.glob("temp/ffanchor_*"))
        ff_err, ff_body, _ = _dispatch_and_poll_pk(
            session,
            base,
            "function_finder_2D",
            base + "/FunctionFinder__F__/2/",
            _FF_2D_FIELDS,
            timeout_s=900,
        )
        if ff_err or ff_body is None:
            errors.append(ff_err or "[function_finder_2D] ranking produced no body")
            ff_body = ""
        else:
            err = _check_markers("function_finder_2D", ff_body, _FF_EXPECTED_MARKERS)
            if err:
                errors.append(err)
                ff_body = ""
            else:
                print("[function_finder_2D] OK")
                # A completed ranking must drop an ffanchor_<pk> retention marker
                # in temp/ (the disk-bounded anchor for the shareable
                # /Results/<token>/ link). Compare against the pre-dispatch
                # snapshot so a stale marker from a prior run can't mask a broken
                # writer.
                if set(glob.glob("temp/ffanchor_*")) - ff_anchors_before:
                    print("[function_finder_2D anchor] OK")
                else:
                    errors.append(
                        "[function_finder_2D] no new temp/ffanchor_* retention "
                        "marker after ranking completion"
                    )

        # Scenario 3: detailed fit of the top-ranked equation (skip if scenario 2 failed)
        if ff_body:
            err = _run_ff_detail_scenario(
                session,
                base,
                "function_finder_detail_2D",
                ff_body,
                timeout_s=600,
            )
            if err:
                errors.append(err)
            else:
                print("[function_finder_detail_2D] OK")

        # Scenario 3b: cross-session shareability of the FunctionFinder result.
        if ff_body:
            err = _run_ff_cross_session_scenario(
                base,
                "function_finder_cross_session_2D",
                ff_body,
                timeout_s=600,
            )
            if err:
                errors.append(err)
            else:
                print("[function_finder_cross_session_2D] OK")

        err = _run_scenario(
            session,
            base,
            "characterize_2D",
            base + "/CharacterizeData/2/",
            _CHAR_2D_FIELDS,
            _CHAR_EXPECTED_MARKERS,
            timeout_s=120,
        )
        if err:
            errors.append(err)
        else:
            print("[characterize_2D] OK")

        # characterize_3D: CharacterizeData with 3D data AND animationSize
        # enabled, to exercise ScatterAnimation's PillowWriter path. Polls by pk
        # like the 2D scenarios; the extra step is the ScatterAnimation GIF
        # check ("san") on the completed body — 3D-specific, not in the 2D path.
        char3d_err, char3d_body, _ = _dispatch_and_poll_pk(
            session,
            base,
            "characterize_3D",
            base + "/CharacterizeData/3/",
            _CHAR_3D_FIELDS,
            timeout_s=300,
        )
        if char3d_err or char3d_body is None:
            errors.append(char3d_err or "[characterize_3D] produced no body")
        else:
            err = _check_markers("characterize_3D", char3d_body, _CHAR_EXPECTED_MARKERS)
            if err:
                errors.append(err)
            else:
                err = _check_animation_gif(session, base, char3d_body, "san")
                if err:
                    errors.append(err)
                else:
                    print("[characterize_3D] OK")

        # polynomial_quadratic_3D: 3D fit with animationSize enabled, to
        # exercise both SurfaceAnimation (fitted-surface rotation) and
        # ScatterAnimation (data-point rotation) via PillowWriter. Polls by pk
        # like the 2D fit; the extra step is the SurfaceAnimation GIF check
        # ("sua") on the completed body — 3D-specific, not in the 2D path.
        poly3d_err, poly3d_body, _ = _dispatch_and_poll_pk(
            session,
            base,
            "polynomial_quadratic_3D",
            base + "/FitEquation__F__/3/Polynomial/Full%20Quadratic/",
            _POLY_QUAD_3D_FIELDS,
            timeout_s=300,
        )
        if poly3d_err or poly3d_body is None:
            errors.append(poly3d_err or "[polynomial_quadratic_3D] produced no body")
        else:
            err = _check_markers("polynomial_quadratic_3D", poly3d_body, _POLY_EXPECTED_MARKERS)
            if err:
                errors.append(err)
            else:
                err = _check_animation_gif(session, base, poly3d_body, "sua")
                if err:
                    errors.append(err)
                else:
                    print("[polynomial_quadratic_3D] OK")

        r = session.get(base + "/AllEquations/2/Polynomial/")
        err = _check_markers("all_equations_2D", r.text, _ALL_EQUATIONS_MARKERS)
        if err:
            errors.append(err)
        else:
            print("[all_equations_2D] OK")

        r = session.post(
            base + "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/",
            data=_INVALID_FIELDS,
            allow_redirects=True,
        )
        err = _check_markers("invalid_form_post", r.text, _INVALID_MARKERS)
        if err:
            errors.append(err)
        else:
            print("[invalid_form_post] OK")

        # spline_2D + round-trip through EvaluateAtAPointView. The
        # round-trip is the real target — FitSpline stores scipySpline as a
        # tuple of ndarrays which NumpySessionSerializer coerces to
        # [list, list, int] at session-write time. EvaluateAtAPointView at
        # views.py:98 loads this verbatim and scipy's splev/BSpline path
        # consumes it.
        err, result_url = _run_scenario_capturing_url(
            session,
            base,
            "spline_2D",
            base + "/FitEquation__F__/2/Spline/Spline/",
            _SPLINE_2D_FIELDS,
            _SPLINE_EXPECTED_MARKERS,
            timeout_s=600,
        )
        if err:
            errors.append(err)
        else:
            print("[spline_2D] OK")
            token = _extract_token_from_results_url(result_url or "")
            if token is None:
                errors.append(
                    f"[evaluate_at_a_point_spline] could not extract token from results URL: "
                    f"{result_url!r}"
                )
            else:
                r = session.post(
                    base + f"/EvaluateAtAPoint/{token}/",
                    data=_EVAL_AT_POINT_FIELDS,
                    allow_redirects=True,
                )
                err = _check_markers("evaluate_at_a_point_spline", r.text, _EVAL_AT_POINT_MARKERS)
                if err:
                    errors.append(err)
                else:
                    print("[evaluate_at_a_point_spline] OK")

        # udf_2D + round-trip through EvaluateAtAPointView. Exercises
        # FitUserDefinedFunction's solvedCoefficients write (coerced to a
        # list by NumpySessionSerializer) and EvaluateAtAPointView's load site.
        err, result_url = _run_scenario_capturing_url(
            session,
            base,
            "udf_2D",
            base + "/FitEquation__F__/2/UserDefinedFunction/UserDefinedFunction/",
            _UDF_2D_FIELDS,
            _POLY_EXPECTED_MARKERS,
            timeout_s=600,
        )
        if err:
            errors.append(err)
        else:
            print("[udf_2D] OK")
            token = _extract_token_from_results_url(result_url or "")
            if token is None:
                errors.append(
                    f"[evaluate_at_a_point_udf] could not extract token from results URL: "
                    f"{result_url!r}"
                )
            else:
                r = session.post(
                    base + f"/EvaluateAtAPoint/{token}/",
                    data=_EVAL_AT_POINT_FIELDS,
                    allow_redirects=True,
                )
                err = _check_markers("evaluate_at_a_point_udf", r.text, _EVAL_AT_POINT_MARKERS)
                if err:
                    errors.append(err)
                else:
                    print("[evaluate_at_a_point_udf] OK")

        # concurrent_2D: two fits in one session with per-dispatch isolation.
        # Uses a FRESH requests.Session (NOT the shared `session` above) so the
        # server sees it as a brand-new browser session — the shared session
        # accumulated lrp_status_pk and data from 10+ previous scenarios and its
        # per-session cap slot may be occupied by a recent non-terminal row.
        # A fresh session starts clean and can admit two new dispatches without
        # racing prior scenario state. The scenario warms cookie_test itself via
        # a fit-interface GET (HomePageView is cached by now and would not).
        concurrent_session = requests.Session()
        concurrent_session.get(base + "/")  # mint the sessionid cookie
        err = _run_concurrent_2D_scenario(
            concurrent_session,
            base,
            timeout_s=600,
        )
        if err:
            errors.append(err)
        else:
            print("[concurrent_2D] OK")

        if errors:
            for msg in errors:
                print("ERROR:", msg, file=sys.stderr)
            return 1
        print("SMOKE OK: all scenarios passed")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ZunZunNG smoke test")
    parser.add_argument(
        "--scenario",
        choices=["default", "function-finder-2D-large", "concurrent-2D"],
        default="default",
        help=(
            "Which smoke scenarios to run. 'default' runs the full ~14-scenario "
            "sequence (most regressions). 'function-finder-2D-large' runs ONLY "
            "the larger FunctionFinder scenario in isolation, useful for "
            "parallel-perf acceptance runs. 'concurrent-2D' runs ONLY the "
            "concurrent-fits isolation scenario."
        ),
    )
    args = parser.parse_args()
    sys.exit(run_smoke(scenario=args.scenario))
