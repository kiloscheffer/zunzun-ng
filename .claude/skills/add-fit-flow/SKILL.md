---
name: add-fit-flow
description: Add a new curve-fit flow to ZunZunNG. Use when introducing a new LRP class (new spline type, polynomial variant, custom fit) that must be wired into the URL dispatcher and LongRunningProcess package. Not for edits to existing fit flows.
disable-model-invocation: true
---

# Adding a new fit flow

A new fit type requires **three coordinated edits**. Missing any one causes the dispatcher to fall through to `FitOneEquation` (wrong class) or return "I could not understand the web request."

## Anatomy

```
urls.py            ──►  LongRunningProcessView  ──► substring-matches request.path
                              (zunzun/views.py)         picks LRP subclass
                                                   ──► LRP.PerformAllWork()
                                                        (zunzun/LongRunningProcess/Fit*.py)
```

## Checklist

### 1. URL pattern in `urls.py`

Add to **both** the `try:` (newer Django, `patterns(...)`) and `except:` (older Django, `[url(...)]`) branches. Dimensionality capture must stay as `([23])` or `([123])` depending on whether 1D is supported.

```python
(r"^MyNewFit__F__/([23])/(.+)/(.+)/$", zunzun.views.LongRunningProcessView),
```

### 2. Dispatcher branch in `zunzun/views.py`

Inside `LongRunningProcessView`, find the cascade starting around line 247:

```python
if -1 != request.path.find('FitEquation__F__/') or -1 != request.path.find('Equation/'):
    if -1 != request.path.find('UserDefinedFunction'):
        LRP = LongRunningProcess.FitUserDefinedFunction.FitUserDefinedFunction()
    ...
```

Add your branch **before** the generic fallbacks. The substring must be unique — collisions (e.g. both `'Polynomial'` and `'Polyfunctional'` matching) are resolved by order, so place the more-specific match first.

### 3. LRP subclass in `zunzun/LongRunningProcess/`

Create `FitMyNewFit.py` using the scaffold in this skill's `fit_template.py`. Then register it in `zunzun/LongRunningProcess/__init__.py`:

```python
from . import FitMyNewFit
```

## Contracts every LRP subclass must honor

Derived from `StatusMonitoredLongRunningProcessPage` and `FittingBaseClass`:

- **`userInterfaceRequired`** (bool): if `True`, `LongRunningProcessView` renders `self.interfaceString` on GET before accepting POST.
- **`interfaceString`**: template path for the interface form (e.g. `'zunzun/equation_fit_interface.html'`).
- **`reniceLevel`** (int, default 10): applied via `os.nice()` in the forked child.
- **`TransferFormDataToDataObject(request)`**: returns an error string (shown to user) or empty string on success.
- **`SetInitialStatusDataIntoSessionVariables(request)`**: pickle-hex-encodes initial status values before fork.
- **`GenerateListOfWorkItems()`** / **`PerformWorkInParallel()`**: overridden by subclass; called from `PerformAllWork()`.

## Traps

- **Do not add a new session store.** The three keys `session_key_status`/`_data`/`_functionfinder` already exist. Reuse them.
- **Wrap every `session.save()` in the 10-second retry loop.** See `StatusMonitoredLongRunningProcessPage.SaveDictionaryOfItemsToSessionStore` for the canonical pattern — SQLite locks under fork contention without it.
- **Write the final redirect target to `redirectToResultsFileOrURL`** in the status session. `StatusView` looks for this key to transition from polling to results.
- **Call `db.connections.close_all()` before `os.fork()`.** Fork-inheriting an open DB connection causes lock chaos.

## After wiring

Run the FunkLoad suite via the `run-funkload` skill and add an assertion block to `funkload_tests/test_Simple.py` for the new endpoint.
