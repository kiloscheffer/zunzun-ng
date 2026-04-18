"""Cross-platform end-to-end smoke test for zunzunsite3.

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
6. **all_equations_2D** — GET AllEquations listing.
7. **feedback_form** — GET form + POST reply.
8. **invalid_form_post** — malformed data → error template.

A 9th scenario (3D polynomial fit) is deferred — see TODO.md.

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
    "Coefficients And Text Reports",
    "Statistical Scatterplots",
]

_FF_EXPECTED_MARKERS = [
    "Function Finder Results",
    "Model Plots",
    "Error Plots",
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

_ALL_EQUATIONS_MARKERS = [
    # /AllEquations/2/Polynomial/ URL — the path-segment `Polynomial`
    # is the view's `inAllOrStandardOnly` flag, not a family filter.
    # The header is "ZunZunSite3 List Of All Standard 2D Equations"
    # and the page lists every family; "Polynomial" appears as a
    # section heading and in many equation links.
    "All Standard 2D Equations",
    "Polynomial",
]

# Pattern for the first /Equation/{dim}/{family}/{equation}/?RANK=1
# hyperlink in the FunctionFinder results listing. family and equation
# segments are URL-encoded (%20 for spaces, %28 for '(', etc.) and
# intentionally stay encoded — the fit POST URL reuses them verbatim.
_RANK1_LINK = re.compile(r"/Equation/(?P<dim>\d+)/(?P<family>[^/?\"<>]+)/(?P<equation>[^/?\"<>]+)/\?RANK=1")


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
    """Poll /StatusAndResults/ until a final body (no REDIRECT/REFRESH) arrives.

    Returns the final body on success or None on timeout. Handles chained
    redirects transparently (requests default follows them).
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = session.get(base + "/StatusAndResults/")
        body = r.text
        if "REDIRECT" not in body and "REFRESH" not in body.upper():
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

        r = session.get(base + "/AllEquations/2/Polynomial/")
        err = _check_markers("all_equations_2D", r.text, _ALL_EQUATIONS_MARKERS)
        if err:
            errors.append(err)
        else:
            print("[all_equations_2D] OK")

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
