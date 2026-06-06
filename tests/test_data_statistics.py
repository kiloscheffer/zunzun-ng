"""DataObject.CalculateStatisticsForList tests.

Regression guard: mean / median / variance / std were computed via
scipy.mean / scipy.median / scipy.var / scipy.std — top-level numpy aliases
that modern scipy (1.x) REMOVED. The bare try/except in
CalculateStatisticsForList swallowed the resulting AttributeError, so those
four stats silently rendered as 'n/a' on the Data Statistics report while the
scipy.stats.* ones (sem / skew / kurtosis) and builtin min/max kept working.
They must use numpy instead.
"""

import numpy
import pytest

from zunzun.LongRunningProcess.DataObject import DataObject


def test_calculate_statistics_populates_all_keys():
    data = [0.607, 3.017, 1.969, 2.0, 1.5, 2.5, 0.9]
    obj = DataObject()
    obj.CalculateStatisticsForList("X", data)

    # The four that regressed to n/a (removed scipy.* aliases):
    assert obj.statistics["X_mean"] == pytest.approx(numpy.mean(data))
    assert obj.statistics["X_median"] == pytest.approx(numpy.median(data))
    assert obj.statistics["X_var"] == pytest.approx(numpy.var(data))
    assert obj.statistics["X_std"] == pytest.approx(numpy.std(data))

    # The five that always worked (builtins + scipy.stats.*), as a guard that
    # the fix didn't disturb them.
    for key in ("X_min", "X_max", "X_sem", "X_skew", "X_kurtosis"):
        assert key in obj.statistics, f"missing {key}"


def test_statistic_failure_is_logged_not_silently_swallowed(monkeypatch, caplog):
    """A statistic that raises must be LOGGED, not silently swallowed, and must
    not abort the remaining statistics.

    The silent ``except: pass`` is exactly what let the scipy.mean/median/var/
    std removal degrade four stats to 'n/a' on the report for a long time with
    no signal. This pins the louder behavior so a future library removal can't
    go invisible again.
    """
    import logging

    from zunzun.LongRunningProcess import DataObject as dataobject_module

    def boom(_data):
        raise RuntimeError("simulated library removal")

    # Make one optional statistic raise the way a removed library function would.
    monkeypatch.setattr(dataobject_module.numpy, "mean", boom)

    obj = DataObject()
    with caplog.at_level(logging.WARNING):
        obj.CalculateStatisticsForList("X", [1.0, 2.0, 3.0])

    # The failing statistic is absent but its failure was logged ...
    assert "X_mean" not in obj.statistics
    assert any("_mean" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING), (
        caplog.text
    )
    # ... and the other statistics still computed (non-fatal).
    assert "X_median" in obj.statistics
    assert "X_min" in obj.statistics
