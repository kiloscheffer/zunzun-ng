"""Cross-platform end-to-end smoke test for zunzunsite3.

Starts a Waitress subprocess on a free port, runs two scenarios against it,
then stops the server. Exits 0 iff both scenarios pass.

Scenarios
---------

1. **Polynomial quadratic 2D direct fit** — POSTs to
   /FitEquation__F__/2/Polynomial/2nd Order (Quadratic)/ with the same
   10-point XY data FunkLoad's test_Simple.py used. Exercises the main
   LongRunningProcessView → spawn → _run_fit_child → PerformAllWork path.

2. **FunctionFinder 2D** — POSTs to /FunctionFinder__F__/2/ with the
   default 11-point dataset pre-filled on the FunctionFinder form.
   Exercises the two-phase ranking → detailed-fit pipeline, including
   the spawned Pool workers inside FunctionFinder.PerformWorkInParallel
   that rely on dataCache being passed through Process args (a bug in
   the original fork-era global-state pattern).

Both scenarios assert structural markers on the final results page —
"Coefficient and Fit Statistics", "Minimum:", "Maximum:" — rather than
exact numerical coefficients, because pyeq3/numpy/scipy version drift
changes the exact values while the structure stays stable.

Usage:
  uv run python scripts/smoke_test.py
"""
import contextlib
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
# Monotonic increasing Y — a fittable shape that all equation families
# can score against.
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

# Minimal FunctionFinder fields. Two equation families is enough to
# exercise the Pool-worker flow without testing hundreds of equations.
# smoothnessControl2D=2 keeps per-equation coefficient count tiny so
# the ranking phase completes quickly even on Windows spawn.
_FF_2D_FIELDS = {
    "commaConversion": "I",
    "dataNameX": "X Data",
    "dataNameY": "Y Data",
    "smoothnessControl2D": "2",
    "smoothnessExactOrMax": "M",
    "equationFamilyInclusion": ["Polynomial", "Exponential"],
    "extendedEquationTypes": ["STANDARD"],
    "fittingTarget": "SSQABS",
    "logLinX": "LIN",
    "logLinY": "LIN",
    "logLinZ": "LIN",
    "textDataEditor": _DATA_2D_FF,
}

# Different scenarios land on different pages. Polynomial direct-fit ends
# at the per-equation detailed results; FunctionFinder ends at the ranking
# listing showing model-plot thumbnails for each equation's rank. The two
# pages share no reliable marker strings, so we assert per-scenario.
# See module docstring on why we don't assert exact numerical values.

_POLY_EXPECTED_MARKERS = [
    "Coefficient and Fit Statistics",
    "Coefficient Covariance Matrix",
    "Minimum:",
    "Maximum:",
]

_FF_EXPECTED_MARKERS = [
    # The results-listing page's header text
    "Function Finder Results",
    # The column headers above each equation's plot row
    "Model Plots",
    "Error Plots",
    # The rank label next to the #1 best-fit equation
    "Rank 1",
]


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


def _run_scenario(
    session: requests.Session,
    base: str,
    name: str,
    post_url: str,
    form_fields: dict,
    expected_markers: list[str],
    timeout_s: float,
) -> str | None:
    """POST to `post_url`, poll /StatusAndResults/ until the fit completes,
    verify structural markers on the final body. Returns None on success
    or an error string on failure.

    The polling loop follows redirects automatically (requests default).
    For scenarios with chained redirects — FunctionFinder completes its
    ranking phase by 302'ing to /FunctionFinderResults/?RANK=1, which
    spawns the detailed-fit phase and 302's back to /StatusAndResults/ —
    requests handles the chain transparently and we keep polling until
    /StatusAndResults/ returns a 200 that contains neither "REFRESH" nor
    "REDIRECT". That's the final results HTML.
    """
    session.post(post_url, data=form_fields, allow_redirects=True)

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = session.get(base + "/StatusAndResults/")
        body = r.text
        if "REDIRECT" not in body and "REFRESH" not in body.upper():
            # Final page reached — check structural markers
            missing = [m for m in expected_markers if m not in body]
            if missing:
                dump_path = f"temp/_smoke_last_body_{name}.html"
                try:
                    with open(dump_path, "w", encoding="utf-8") as _f:
                        _f.write(body)
                except Exception:
                    pass
                preview = body[:2000]
                return (
                    f"[{name}] missing markers: {missing}\n"
                    f"full body written to {dump_path} ({len(body)} chars)\n"
                    f"--- preview (first 2000 chars) ---\n{preview}\n--- end ---"
                )
            return None
        time.sleep(3)

    return f"[{name}] fit did not complete within {int(timeout_s)}s"


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
        # Hit homepage once to establish the session cookie. Must be
        # AFTER the readiness probe (not as part of it) so the cookie
        # lands on `session`, not discarded in a throwaway request.
        session.get(base + "/")

        errors = []

        # Scenario 1: direct polynomial-quadratic fit (~1 min on Linux fork,
        # ~3 min on Windows spawn for the smoke data).
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

        # Scenario 2: FunctionFinder 2D — two-phase ranking → results listing.
        # Phase 1 ranks all equations in the enabled families; phase 2 renders
        # the top-N results page with model-plot thumbnails for each rank.
        # Final landing is the ranking listing (not a per-equation fit page).
        err = _run_scenario(
            session,
            base,
            "function_finder_2D",
            base + "/FunctionFinder__F__/2/",
            _FF_2D_FIELDS,
            _FF_EXPECTED_MARKERS,
            timeout_s=900,
        )
        if err:
            errors.append(err)
        else:
            print("[function_finder_2D] OK")

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
