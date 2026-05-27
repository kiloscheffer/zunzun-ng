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
5. **characterize_2D** — descriptive statistics only, no fit.
6. **characterize_3D** — 3D characterize with animationSize enabled;
   verifies the ScatterAnimation GIF loads with ≥2 frames.
7. **polynomial_quadratic_3D** — 3D full-quadratic fit with animation
   enabled; verifies the SurfaceAnimation GIF loads with ≥2 frames.
8. **all_equations_2D** — GET AllEquations listing.
9. **feedback_form** — GET form + POST reply.
10. **invalid_form_post** — malformed data → error template.
11. **spline_2D** — 2D cubic spline fit with smoothness=1.0, chained into
    an `/EvaluateAtAPoint/` POST to verify the `_json_native`-mangled
    `scipySpline` round-trips through the session.
12. **udf_2D** — 2D User Defined Function fit with formula `a + b*X`,
    chained into an `/EvaluateAtAPoint/` POST to verify
    `solvedCoefficients` round-trips through the session.

Usage:
  uv run python scripts/smoke_test.py
"""
import contextlib
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

# FeedbackView GET redirects to '/' (home page), so there is no form-
# rendering GET to anchor on. The POST path is the only render_to_response
# site exercised here (feedback_reply.html). Field names must match
# FeedbackForm: feedbackText and emailAddress.
_FEEDBACK_POST_FIELDS = {
    "feedbackText": "Automated smoke test submission — please ignore.",
    "emailAddress": "smoke@example.com",
}

_FEEDBACK_POST_MARKERS = [
    "Thank you",
]

# /Feedback/ GET redirects to '/'; we only assert the redirect lands
# somewhere that renders the home page (non-empty, contains ZunZunNG).
_FEEDBACK_GET_MARKERS = [
    "ZunZunNG",
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
_RANK1_LINK = re.compile(r"/Equation/(?P<dim>\d+)/(?P<family>[^/?\"<>]+)/(?P<equation>[^/?\"<>]+)/\?RANK=1")


def _check_animation_gif(session, base, body, name_prefix, min_frames=2):
    """Find a /temp/{name_prefix}*.gif href in body, read that file
    directly off disk, verify the bytes load as a GIF with ≥min_frames
    animated frames.

    Returns None on success, or an error string on failure.

    Used by the 3D scenarios to confirm matplotlib.animation.PillowWriter
    actually produced a multi-frame animated GIF. The name_prefix is
    `ScatterAnimation` (for CharacterizeData output) or `SurfaceAnimation`
    (for fit output); both are constants set on GraphReport subclasses
    in zunzun/LongRunningProcess/ReportsAndGraphs.py.

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
        return f"[{name_prefix}] no /temp/{name_prefix}*.gif href found in response body"
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
        except (OSError, ConnectionRefusedError):
            time.sleep(0.5)
    return False


def _poll_until_done(session: requests.Session, base: str, timeout_s: float) -> str | None:
    """Poll /StatusAndResults/ until a final body arrives.

    Detects the in-progress page by the presence of id="currentStatus"
    (a stable marker the status.html template guarantees and the
    StatusPoll.js client depends on). Completion bodies — whether the
    result HTML file served in-place or a result page reached via
    redirect — never contain this marker.

    Returns the final body on success or None on timeout. Handles chained
    redirects transparently (requests default follows them).
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = session.get(base + "/StatusAndResults/")
        body = r.text
        if 'id="currentStatus"' not in body:
            return body
        time.sleep(3)
    return None


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
    session.post(post_url, data=form_fields, allow_redirects=True)
    body = _poll_until_done(session, base, timeout_s)
    if body is None:
        return f"[{name}] did not complete within {int(timeout_s)}s"
    return _check_markers(name, body, expected_markers)


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
    session.post(fit_url, data=detail_fields, allow_redirects=True)

    body = _poll_until_done(session, base, timeout_s)
    if body is None:
        return f"[{name}] detailed fit did not complete within {int(timeout_s)}s"
    return _check_markers(name, body, _POLY_EXPECTED_MARKERS)


def run_smoke() -> int:
    port = _find_free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        ["waitress-serve", f"--listen=127.0.0.1:{port}", "wsgi:application"]
    )
    try:
        if not _wait_for_port(port):
            print("ERROR: server never became ready", file=sys.stderr)
            return 1

        session = requests.Session()
        session.get(base + "/")  # establish session cookie

        errors = []

        # Scenario 1: direct polynomial-quadratic fit
        err = _run_scenario(
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
            r = session.post(
                base + "/EvaluateAtAPoint/",
                data=_EVAL_AT_POINT_FIELDS,
                allow_redirects=True,
            )
            err = _check_markers("evaluate_at_a_point", r.text, _EVAL_AT_POINT_MARKERS)
            if err:
                errors.append(err)
            else:
                print("[evaluate_at_a_point] OK")

        # Scenario 2: FunctionFinder ranking. Capture the final body for scenario 3.
        session.post(
            base + "/FunctionFinder__F__/2/",
            data=_FF_2D_FIELDS,
            allow_redirects=True,
        )
        ff_body = _poll_until_done(session, base, timeout_s=900)
        if ff_body is None:
            errors.append("[function_finder_2D] ranking did not complete within 900s")
            ff_body = ""
        else:
            err = _check_markers("function_finder_2D", ff_body, _FF_EXPECTED_MARKERS)
            if err:
                errors.append(err)
            else:
                print("[function_finder_2D] OK")

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
        # enabled, to exercise ScatterAnimation's PillowWriter path.
        session.post(
            base + "/CharacterizeData/3/",
            data=_CHAR_3D_FIELDS,
            allow_redirects=True,
        )
        char3d_body = _poll_until_done(session, base, timeout_s=300)
        if char3d_body is None:
            errors.append("[characterize_3D] did not complete within 300s")
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
        # ScatterAnimation (data-point rotation) via PillowWriter.
        session.post(
            base + "/FitEquation__F__/3/Polynomial/Full%20Quadratic/",
            data=_POLY_QUAD_3D_FIELDS,
            allow_redirects=True,
        )
        poly3d_body = _poll_until_done(session, base, timeout_s=300)
        if poly3d_body is None:
            errors.append("[polynomial_quadratic_3D] did not complete within 300s")
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

        r = session.get(base + "/Feedback/")
        err = _check_markers("feedback_form_get", r.text, _FEEDBACK_GET_MARKERS)
        if err:
            errors.append(err)
        else:
            r = session.post(
                base + "/Feedback/",
                data=_FEEDBACK_POST_FIELDS,
                allow_redirects=True,
            )
            err = _check_markers("feedback_form_post", r.text, _FEEDBACK_POST_MARKERS)
            if err:
                errors.append(err)
            else:
                print("[feedback_form] OK")

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
        # tuple of ndarrays which _json_native converts to [list, list, int]
        # before session write. EvaluateAtAPointView at views.py:98 loads
        # this verbatim and scipy's splev/BSpline path consumes it.
        err = _run_scenario(
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
            r = session.post(
                base + "/EvaluateAtAPoint/",
                data=_EVAL_AT_POINT_FIELDS,
                allow_redirects=True,
            )
            err = _check_markers(
                "evaluate_at_a_point_spline", r.text, _EVAL_AT_POINT_MARKERS
            )
            if err:
                errors.append(err)
            else:
                print("[evaluate_at_a_point_spline] OK")

        # udf_2D + round-trip through EvaluateAtAPointView. Exercises
        # FitUserDefinedFunction's solvedCoefficients write (list after
        # _json_native) and EvaluateAtAPointView's load site.
        err = _run_scenario(
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
            r = session.post(
                base + "/EvaluateAtAPoint/",
                data=_EVAL_AT_POINT_FIELDS,
                allow_redirects=True,
            )
            err = _check_markers(
                "evaluate_at_a_point_udf", r.text, _EVAL_AT_POINT_MARKERS
            )
            if err:
                errors.append(err)
            else:
                print("[evaluate_at_a_point_udf] OK")

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
    sys.exit(run_smoke())
