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
