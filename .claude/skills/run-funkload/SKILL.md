---
name: run-funkload
description: Run the zunzunsite3 FunkLoad functional test suite. Starts the Django dev server if needed, runs fl-run-test against 127.0.0.1:8000, and surfaces pass/fail assertions. Use for verifying fit flows end-to-end since there is no pytest/manage.py test target.
---

# Running FunkLoad tests

Tests live in `funkload_tests/` and drive a **live HTTP server** — they are not collected by `pytest` or `manage.py test`.

## One-shot: full suite

In two terminals:

```bash
# terminal 1: dev server (must match URL in Simple.conf)
python3 manage.py runserver 127.0.0.1:8000

# terminal 2: tests
cd funkload_tests
fl-run-test -v test_Simple.py Simple.test_simple
```

## Single test file

```bash
cd funkload_tests
fl-run-test -v test_Characterizer2D.py
fl-run-test -v test_PolynomialLinearWithExponentialDecay_SSQABS.py
```

## Toggling individual assertion blocks

`test_Simple.py` gates each block on a module-level boolean near the top:

```python
testCharacterizers = True
testPolynomialQuadratic2D_SSQABS = True
testSpline2D = False   # flip to True to run
testUserDefinedFunction2D = True
testFunctionFinder2D = True
```

Flip the flag rather than commenting out blocks or creating new test files.

## Prerequisites

- `pip install funkload` (not in README's apt list; it is a pip-only package).
- The dev server must be reachable at the URL in `funkload_tests/Simple.conf` under `[main] url=` — default is `http://127.0.0.1:8000`.

## Interpreting output

- Each assertion in `Simple.PostLongRunningProcess` checks a **substring** inside the rendered results page. Numeric expectations (e.g. `'Minimum: 5.084392E+00'`) are tied to the default example data in `DefaultData.py`; if you change the default data or the fitting math, these strings must be updated.
- A 240-second per-test timeout is baked in. A test hang usually means the forked child died silently — check `temp/*.log` for logged exceptions from `PerformAllWork()`.

## Cleanup

On success the test leaves behind `simple-test.xml` and `simple-test.log` in `funkload_tests/`. `tearDown` tries to delete them but only removes files containing `'xml'` in the name.
