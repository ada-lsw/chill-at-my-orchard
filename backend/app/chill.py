"""Chill and heat models, matched to FNRIC's definitions.

Source: FNRIC hackathon cheat sheet (github.com/ucdavis/fnric-reboot-the-eath-hackathon)
and fruitsandnuts.ucdavis.edu/about-chilling-hours-units-and-portions.

Input: hourly air temperatures in °F (NaN = missing hour).
Check results against FNRIC's chill calculator: if the totals match, the math is right.
"""
from __future__ import annotations

from math import asin, cos, pi

import numpy as np
import pandas as pd

from . import config


def f_to_c(t):
    return (np.asarray(t, dtype=float) - 32.0) * 5.0 / 9.0


# ---------------------------------------------------------------- hour counts

def hours_below(temps_f, threshold_f: float, inclusive: bool = True) -> np.ndarray:
    """Cumulative hours at or below a threshold. Missing hours count as 0."""
    t = np.asarray(temps_f, dtype=float)
    hit = t <= threshold_f if inclusive else t < threshold_f
    return np.cumsum(np.where(np.isnan(t), 0, hit))


def hours_between(temps_f, low_f: float, high_f: float) -> np.ndarray:
    """Cumulative hours with low < T <= high (FNRIC's boundary convention)."""
    t = np.asarray(temps_f, dtype=float)
    hit = (t > low_f) & (t <= high_f)
    return np.cumsum(np.where(np.isnan(t), 0, hit))


def hours_above(temps_f, threshold_f: float) -> np.ndarray:
    """Cumulative hours above a threshold."""
    t = np.asarray(temps_f, dtype=float)
    return np.cumsum(np.where(np.isnan(t), 0, t > threshold_f))


def chill_hours_lt45(temps_f) -> np.ndarray:
    """FNRIC 'hours below 45°F': 1 if T <= 45 (API field hours_lt_45)."""
    return hours_below(temps_f, 45.0)


def chill_hours(temps_f) -> np.ndarray:
    """FNRIC 'hours 32–45°F': 1 if 32 < T <= 45 (API field hours_32_45)."""
    return hours_between(temps_f, 32.0, 45.0)


# ---------------------------------------------------------------- Utah

# FNRIC's Utah bins, °F, upper edge inclusive. Warm hours subtract.
UTAH_BINS_F = [  # (upper edge, units per hour)
    (34.0, 0.0),    # <= 34
    (36.0, 0.5),    # 34–36
    (48.0, 1.0),    # 36–48  (most effective)
    (54.0, 0.5),    # 48–54
    (60.0, 0.0),    # 54–60
    (65.0, -0.5),   # 60–65
]
UTAH_ABOVE = -1.0   # > 65


def utah_units(temps_f) -> np.ndarray:
    """Cumulative Utah chill units, FNRIC bins (API field units_utah)."""
    t = np.asarray(temps_f, dtype=float)
    w = np.select([t <= edge for edge, _ in UTAH_BINS_F],
                  [v for _, v in UTAH_BINS_F], default=UTAH_ABOVE)
    return np.cumsum(np.where(np.isnan(t), 0, w))


# ---------------------------------------------------------------- Dynamic model

def chill_portions(temps_f, e0=4153.5, e1=12888.8, a0=139500.0, a1=2.567e18,
                   slope=1.6, tf=277.0) -> np.ndarray:
    """Cumulative chill portions, Dynamic Model (Fishman et al. 1987; Erez et al. 1990).

    Stateful: missing hours are filled with the previous valid value first.
    """
    t = pd.Series(np.asarray(temps_f, dtype=float)).ffill().bfill().to_numpy()
    n = len(t)
    if n == 0:
        return np.array([])
    tk = f_to_c(t) + 273.0
    ftmprt = slope * tf * (tk - tf) / tk
    sr = np.exp(ftmprt)
    xi = sr / (1.0 + sr)
    xs = (a0 / a1) * np.exp((e1 - e0) / tk)
    eak1 = np.exp(-a1 * np.exp(-e1 / tk))

    x = np.zeros(n)
    delta = np.zeros(n)
    for i in range(1, n):
        s = x[i - 1]
        if s >= 1.0:
            s = s * (1.0 - xi[i - 1])
        x[i] = xs[i - 1] - (xs[i - 1] - s) * eak1[i - 1]
        if x[i] >= 1.0:
            delta[i] = x[i] * xi[i]
    return np.cumsum(delta)


# ---------------------------------------------------------------- GDD

def gdd_single_sine(tmin_c: float, tmax_c: float, lo: float = 5.0, hi: float = 35.0) -> float:
    """One day's degree-days, single-sine method (Zalom et al. 1983), °C.

    Port of FNRIC's function: lower threshold 5°C (41°F), upper 35°C (95°F).
    """
    if np.isnan(tmin_c) or np.isnan(tmax_c):
        return 0.0
    mean, a = (tmax_c + tmin_c) / 2, (tmax_c - tmin_c) / 2
    if tmin_c >= hi:
        return hi - lo
    if tmax_c <= lo:
        return 0.0
    if tmax_c <= hi and tmin_c >= lo:
        return mean - lo
    if tmax_c <= hi:  # tmin < lo
        s1 = asin((lo - mean) / a)
        return ((mean - lo) * (pi / 2 - s1) + a * cos(s1)) / pi
    if tmin_c >= lo:  # tmax > hi
        s2 = asin((hi - mean) / a)
        return ((mean - lo) * (s2 + pi / 2) + (hi - lo) * (pi / 2 - s2) - a * cos(s2)) / pi
    s1, s2 = asin((lo - mean) / a), asin((hi - mean) / a)
    return ((mean - lo) * (s2 - s1) + a * (cos(s1) - cos(s2)) + (hi - lo) * (pi / 2 - s2)) / pi


def gdd_cumulative(tmax_f, tmin_f, lo_c: float = 5.0, hi_c: float = 35.0) -> np.ndarray:
    """Cumulative single-sine GDD in °C·days from daily max/min in °F."""
    tmax_c, tmin_c = f_to_c(tmax_f), f_to_c(tmin_f)
    daily = [gdd_single_sine(lo_t, hi_t, lo_c, hi_c) for lo_t, hi_t in zip(tmin_c, tmax_c)]
    return np.cumsum(daily)


# ---------------------------------------------------------------- summary

def summarize(hourly: pd.Series, crop: str = "almond",
              custom_range: tuple[float, float] | None = None) -> dict:
    """Season-to-date totals from an hourly °F series indexed by datetime."""
    hourly = hourly.sort_index()
    empty = len(hourly) == 0
    last = lambda arr: 0.0 if empty else float(arr[-1])  # noqa: E731
    out = {
        "hours_counted": int(hourly.notna().sum()),
        "hours_missing": int(hourly.isna().sum()),
        "chill_hours": last(chill_hours(hourly)),          # 32 < T <= 45
        "hours_lt_45": last(chill_hours_lt45(hourly)),     # T <= 45
        "utah_units": last(utah_units(hourly)),
        "chill_portions": last(chill_portions(hourly)),
    }
    if custom_range:
        lo, hi = custom_range
        out["custom_range"] = {
            "low_f": lo, "high_f": hi,
            "hours_below": last(hours_below(hourly, lo)),
            "hours_between": last(hours_between(hourly, lo, hi)),
            "hours_above": last(hours_above(hourly, hi)),
        }
    daily = hourly.resample("D").agg(["max", "min"]).dropna()
    lo_c, hi_c = config.GDD_THRESHOLDS_C.get(crop, (5.0, 35.0))
    out["gdd"] = last(gdd_cumulative(daily["max"], daily["min"], lo_c, hi_c)) if len(daily) else 0.0
    out["gdd_thresholds_c"] = [lo_c, hi_c]
    return out
