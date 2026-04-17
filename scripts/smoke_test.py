"""Cross-platform end-to-end smoke test for zunzunsite3.

Starts a Waitress subprocess on a free port, POSTs a 2D polynomial-
quadratic fit against the default sample data, polls /StatusAndResults/
until the fit completes, asserts on known numeric coefficients, then
stops the server. Exits 0 on success, nonzero on failure.

Reference coefficients (from funkload_tests/test_Simple.py — preserved
here because FunkLoad no longer runs):
  Minimum: -5.824100E-02, -5.610455E-02
  Maximum:  7.692989E-02,  1.154094E-02

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


# Sample data lifted from funkload_tests/test_Simple.py default_data2D
_DATA_2D = """X Y
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

_FORM_FIELDS = {
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
    "textDataEditor": _DATA_2D,
}

_EXPECTED_STRINGS = [
    "-5.824100E-02",
    "-5.610455E-02",
]


def run_smoke() -> int:
    port = _find_free_port()
    base = f"http://127.0.0.1:{port}"
    # Use the installed waitress-serve console script. On uv-managed envs
    # it's on PATH when the script is invoked via `uv run`. No sys.executable
    # wrapper because `python -m waitress` is not a standard entry point.
    proc = subprocess.Popen(
        [
            "waitress-serve",
            f"--listen=127.0.0.1:{port}",
            "wsgi:application",
        ]
    )
    try:
        # Wait for server to be ready
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                requests.get(base + "/", timeout=1)
                break
            except requests.ConnectionError:
                time.sleep(0.5)
        else:
            print("ERROR: server never became ready", file=sys.stderr)
            return 1

        # Get homepage to establish session cookie
        session = requests.Session()
        session.get(base + "/")

        # POST the fit
        session.post(
            base + "/FitEquation__F__/2/Polynomial/2nd%20Order%20(Quadratic)/",
            data=_FORM_FIELDS,
            allow_redirects=True,
        )

        # Poll /StatusAndResults/ until completion (up to 240s)
        poll_deadline = time.time() + 240
        while time.time() < poll_deadline:
            r = session.get(base + "/StatusAndResults/")
            body = r.text
            if "REDIRECT" not in body and "REFRESH" not in body.upper():
                # Done — check expected strings
                for expected in _EXPECTED_STRINGS:
                    if expected not in body:
                        print(
                            f"ERROR: expected '{expected}' not in results",
                            file=sys.stderr,
                        )
                        return 1
                print("SMOKE OK: fit completed and numeric asserts passed")
                return 0
            time.sleep(3)

        print("ERROR: fit did not complete within 240s", file=sys.stderr)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(run_smoke())
