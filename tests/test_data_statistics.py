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
