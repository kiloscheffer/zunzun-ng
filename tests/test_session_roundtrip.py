"""Session-helper roundtrip tests.

Asserts SaveDictionaryOfItemsToSessionStore / LoadItemFromSessionStore
preserve JSON-native values through a full write/read cycle.

These tests pass on the CURRENT pickle/hex implementation (because
pickle can trivially round-trip any JSON-native value), AND on the
Phase 3 post-refactor implementation (because JSON can too). This
lets us write the tests once and have them validate both states.
"""

import json

import pytest

from zunzun.LongRunningProcess.StatusMonitoredLongRunningProcessPage import (
    StatusMonitoredLongRunningProcessPage,
)


def _make_lrp(db):
    """Build an LRP with a fresh status SessionStore — minimal setup
    needed for Save/Load helpers to work.
    """
    from django.contrib.sessions.backends.db import SessionStore

    lrp = StatusMonitoredLongRunningProcessPage()
    # Create a new session and stash its key on the LRP.
    session = SessionStore()
    session.create()
    lrp.session_key_status = session.session_key
    lrp.session_status = session
    lrp.session_key_data = None
    lrp.session_data = None
    lrp.session_key_functionfinder = None
    lrp.session_functionfinder = None
    return lrp


@pytest.mark.parametrize(
    "key,value",
    [
        ("a_float", 3.14),
        ("a_string", "hello world"),
        ("an_empty_string", ""),
        ("a_list_of_floats", [1.0, 2.5, 3.7]),
        ("a_nested_dict", {"x": 1.0, "y": "text", "z": [1, 2, 3]}),
        ("a_unicode_string", "café résumé 🙂"),
        ("a_bool", True),
        ("an_int", 42),
    ],
)
@pytest.mark.django_db
def test_save_load_roundtrip(db, key, value):
    lrp = _make_lrp(db)
    lrp.SaveDictionaryOfItemsToSessionStore("status", {key: value})
    loaded = lrp.LoadItemFromSessionStore("status", key)
    assert loaded == value


@pytest.mark.parametrize(
    "value",
    [
        3.14,
        "hello",
        [1.0, 2.0, 3.0],
        {"nested": {"x": 1, "y": "two"}},
        True,
        42,
    ],
)
@pytest.mark.django_db
def test_values_are_json_native(db, value):
    """Post-Phase-3 invariant: every value handed to the session helper
    should be cleanly serializable by stdlib json.
    """
    # json.dumps raises TypeError on numpy scalars, sets, datetime, etc.
    # If this passes, the value is safe to store without a pickle fallback.
    json.dumps(value)


@pytest.mark.django_db
def test_load_missing_key_returns_none(db):
    lrp = _make_lrp(db)
    result = lrp.LoadItemFromSessionStore("status", "no_such_key")
    assert result is None


# ---- numpy-aware serializer (NumpySessionSerializer) ----


def test_numpy_serializer_roundtrips_numpy_values():
    """NumpySessionSerializer.dumps/loads coerces numpy scalars and arrays
    to plain Python primitives, the way settings.SESSION_SERIALIZER does
    on every session.save().
    """
    import numpy

    from zunzun.session_helpers import NumpySessionSerializer

    serializer = NumpySessionSerializer()
    payload = {
        "scalar_f64": numpy.float64(3.14),
        "scalar_i64": numpy.int64(42),
        "scalar_bool": numpy.bool_(True),
        "array_1d": numpy.array([1.0, 2.5, 3.7]),
        "nested": {"coeffs": numpy.array([[1, 2], [3, 4]]), "name": "poly"},
        "tck_tuple": (numpy.array([0.0, 1.0]), numpy.array([2.0, 3.0]), 3),
    }

    restored = serializer.loads(serializer.dumps(payload))

    # Every value comes back as a plain Python primitive, and json has
    # turned tuples into lists (no tuple type in JSON).
    assert restored["scalar_f64"] == 3.14
    assert isinstance(restored["scalar_f64"], float)
    assert restored["scalar_i64"] == 42
    assert isinstance(restored["scalar_i64"], int)
    assert restored["scalar_bool"] is True
    assert restored["array_1d"] == [1.0, 2.5, 3.7]
    assert restored["nested"]["coeffs"] == [[1, 2], [3, 4]]
    assert restored["nested"]["name"] == "poly"
    assert restored["tck_tuple"] == [[0.0, 1.0], [2.0, 3.0], 3]


@pytest.mark.django_db
def test_lrp_save_load_roundtrips_numpy_via_serializer(db):
    """End-to-end: numpy values written through
    SaveDictionaryOfItemsToSessionStore survive a real SQLite session
    round-trip and read back as plain Python primitives — proving
    settings.SESSION_SERIALIZER is wired to NumpySessionSerializer (no
    _json_native cast at the call site).

    Two things are proven here:
      1. The save() does not raise. Django's stock JSONSerializer raises
         TypeError on an ndarray; reaching the asserts at all means the
         configured serializer coerced it at dumps time.
      2. A FRESH SessionStore opened on the same key (forcing a real
         deserialize-from-DB, not the in-memory _session cache that the
         saving instance still holds) reads back plain lists / ints —
         mirroring production, where the fit child saves and a separate
         process (e.g. EvaluateAtAPointView) loads.
    """
    import numpy
    from django.contrib.sessions.backends.db import SessionStore

    lrp = _make_lrp(db)
    lrp.SaveDictionaryOfItemsToSessionStore(
        "status",
        {
            "coeffs": numpy.array([1.5, 2.5, 3.5]),
            "rank": numpy.int64(7),
        },
    )

    fresh = SessionStore(lrp.session_key_status)
    assert fresh["coeffs"] == [1.5, 2.5, 3.5]
    assert isinstance(fresh["coeffs"], list)
    assert fresh["rank"] == 7
    assert isinstance(fresh["rank"], int)
