"""Checks against FNRIC's definitions (cheat sheet in ucdavis/fnric-reboot-the-eath-hackathon)."""
import numpy as np
import pandas as pd
import pytest

from app import chill


def test_hours_32_45_fnric_boundaries():
    # 32 < T <= 45: 32 itself does not count, 45 does
    assert chill.chill_hours([31, 32, 40, 45, 46, np.nan])[-1] == 2


def test_hours_below_45():
    assert chill.chill_hours_lt45([31, 32, 40, 45, 46, np.nan])[-1] == 4


@pytest.mark.parametrize("temp_f, units", [
    (30, 0.0), (34, 0.0), (35, 0.5), (36, 0.5), (40, 1.0), (48, 1.0),
    (50, 0.5), (54, 0.5), (57, 0.0), (60, 0.0), (62, -0.5), (65, -0.5), (70, -1.0),
])
def test_utah_fnric_bins(temp_f, units):
    assert chill.utah_units([temp_f])[-1] == units


def test_custom_range_counts():
    temps = [20, 33, 44, 50, 80]
    assert chill.hours_below(temps, 32)[-1] == 1
    assert chill.hours_between(temps, 32, 45)[-1] == 2
    assert chill.hours_above(temps, 45)[-1] == 2


def test_chill_portions_cold_vs_warm():
    month = 24 * 30
    cold = chill.chill_portions(np.full(month, 43.0))
    warm = chill.chill_portions(np.full(month, 75.0))
    assert 15 < cold[-1] < 40
    assert warm[-1] == 0
    assert np.all(np.diff(cold) >= 0)


def test_gdd_single_sine_cases():
    assert chill.gdd_single_sine(10, 20) == pytest.approx(10.0)   # fully inside 5–35°C
    assert chill.gdd_single_sine(0, 4) == 0.0                     # never above 5°C
    assert chill.gdd_single_sine(36, 40) == pytest.approx(30.0)   # capped at upper
    partial = chill.gdd_single_sine(0, 10)                        # crosses lower threshold
    assert 0 < partial < 5 - 0  # less than the simple-average answer would allow
    assert chill.gdd_single_sine(20, 40) < (20 + 40) / 2 - 5      # upper cutoff trims heat


def test_summarize_counts_missing():
    idx = pd.date_range("2025-11-01", periods=48, freq="h")
    s = pd.Series(40.0, index=idx)
    s.iloc[5] = np.nan
    out = chill.summarize(s, custom_range=(32, 45))
    assert out["hours_missing"] == 1
    assert out["chill_hours"] == 47
    assert out["custom_range"]["hours_between"] == 47
