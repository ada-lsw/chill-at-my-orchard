"""Chill and heat models. Input: hourly temperatures in °F (NaN = missing hour).

Three chill counts FNRIC uses (hours, Utah units, portions) plus GDD.
Chill portions follow the Dynamic Model as implemented in chillR (Luedeling).
Cross-check one station against chillR before the demo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config


def f_to_c(t):
    return (np.asarray(t, dtype=float) - 32.0) * 5.0 / 9.0


def chill_hours(temps_f) -> np.ndarray:
    """Cumulative hours with 32°F <= T <= 45°F. Missing hours count as 0."""
    t = np.asarray(temps_f, dtype=float)
    hit = (t >= config.CHILL_HOURS_LOW_F) & (t <= config.CHILL_HOURS_HIGH_F)
    return np.cumsum(np.where(np.isnan(t), 0, hit))


def utah_units(temps_f) -> np.ndarray:
    """Cumulative Utah chill units (Richardson et al. 1974). Missing hours count as 0."""
    c = f_to_c(temps_f)
    w = np.select(
        [c <= 1.4, c <= 2.4, c <= 9.1, c <= 12.4, c <= 15.9, c <= 18.0],
        [0.0, 0.5, 1.0, 0.5, 0.0, -0.5],
        default=-1.0,
    )
    return np.cumsum(np.where(np.isnan(c), 0, w))


def chill_portions(temps_f, e0=4153.5, e1=12888.8, a0=139500.0, a1=2.567e18,
                   slope=1.6, tf=277.0) -> np.ndarray:
    """Cumulative chill portions, Dynamic Model (Fishman et al. 1987; Erez et al. 1990).

    Missing hours are filled with the previous valid value before running the model,
    because the model is stateful. Fill gaps upstream when you can.
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

    x = np.zeros(n)          # intermediate product
    delta = np.zeros(n)      # portions completed this hour
    for i in range(1, n):
        s = x[i - 1]
        if s >= 1.0:
            # a portion completed last hour: a share xi of the intermediate was converted
            s = s * (1.0 - xi[i - 1])
        x[i] = xs[i - 1] - (xs[i - 1] - s) * eak1[i - 1]
        if x[i] >= 1.0:
            delta[i] = x[i] * xi[i]
    return np.cumsum(delta)


def gdd_daily(tmax_f, tmin_f, base_f: float) -> np.ndarray:
    """Cumulative growing degree days, simple average method."""
    tmax = np.asarray(tmax_f, dtype=float)
    tmin = np.asarray(tmin_f, dtype=float)
    daily = np.maximum(0.0, (tmax + tmin) / 2.0 - base_f)
    return np.cumsum(np.nan_to_num(daily))


def summarize(hourly: pd.Series, crop: str = "almond") -> dict:
    """Season-to-date totals from an hourly °F series indexed by datetime."""
    hourly = hourly.sort_index()
    out = {
        "hours_counted": int(hourly.notna().sum()),
        "hours_missing": int(hourly.isna().sum()),
        "chill_hours": float(chill_hours(hourly)[-1]) if len(hourly) else 0.0,
        "utah_units": float(utah_units(hourly)[-1]) if len(hourly) else 0.0,
        "chill_portions": float(chill_portions(hourly)[-1]) if len(hourly) else 0.0,
    }
    daily = hourly.resample("D").agg(["max", "min"]).dropna()
    base = config.GDD_BASE_F.get(crop, 50.0)
    out["gdd"] = float(gdd_daily(daily["max"], daily["min"], base)[-1]) if len(daily) else 0.0
    out["gdd_base_f"] = base
    return out
