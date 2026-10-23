import numpy as np
import pandas as pd

from app import chill


def test_chill_hours_window():
    temps = [31, 32, 40, 45, 46, np.nan]
    assert chill.chill_hours(temps)[-1] == 3


def test_utah_weights():
    # 41°F ≈ 5°C -> 1 unit; 70°F ≈ 21°C -> -1 unit
    assert chill.utah_units([41])[-1] == 1.0
    assert chill.utah_units([70])[-1] == -1.0


def test_chill_portions_cold_vs_warm():
    month = 24 * 30
    cold = chill.chill_portions(np.full(month, 43.0))   # ~6°C, near the model's optimum
    warm = chill.chill_portions(np.full(month, 75.0))   # ~24°C, no chill
    assert 15 < cold[-1] < 40
    assert warm[-1] == 0
    assert np.all(np.diff(cold) >= 0)                     # portions never go backwards


def test_gdd_simple_average():
    assert chill.gdd_daily([70, 60], [50, 40], base_f=50)[-1] == 10 + 0


def test_summarize_counts_missing():
    idx = pd.date_range("2025-11-01", periods=48, freq="h")
    s = pd.Series(40.0, index=idx)
    s.iloc[5] = np.nan
    out = chill.summarize(s)
    assert out["hours_missing"] == 1
    assert out["chill_hours"] == 47
