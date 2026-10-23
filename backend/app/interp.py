"""Estimate hourly temperature at any point, and measure how good the estimate is.

Method (v1): inverse-distance weighting of nearby stations after moving each station's
temperature to the target's elevation with a lapse rate. Swap in regression kriging
(PyKrige) later if it validates better; validate.py is the judge.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import requests

from . import config


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def elevation_m(lat: float, lon: float) -> float | None:
    """Terrain height from the Open-Meteo Elevation API (Copernicus 90 m). None if offline."""
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude": lat, "longitude": lon}, timeout=10)
        r.raise_for_status()
        return float(r.json()["elevation"][0])
    except Exception:
        return None


def nearest(stations: pd.DataFrame, lat: float, lon: float, k: int, exclude=()) -> pd.DataFrame:
    s = stations[~stations["station_id"].isin(exclude)].copy()
    s["dist_km"] = haversine_km(lat, lon, s["lat"].to_numpy(), s["lon"].to_numpy())
    return s.nsmallest(k, "dist_km")


def estimate_series(hourly: dict[str, pd.Series], neighbors: pd.DataFrame,
                    target_elev_m: float, lapse_f_per_m: float | None = None,
                    power: float | None = None) -> pd.Series:
    """Weighted estimate at the target for every hour.

    hourly: station_id -> hourly °F series indexed by datetime.
    neighbors: rows with station_id, elev_m, dist_km.
    Hours where a station is missing just drop that station from the weights.
    """
    lapse = config.LAPSE_F_PER_M if lapse_f_per_m is None else lapse_f_per_m
    p = config.IDW_POWER if power is None else power
    cols, weights = {}, {}
    for _, row in neighbors.iterrows():
        s = hourly.get(row.station_id)
        if s is None or s.empty:
            continue
        # move this station's temperature to the target elevation
        cols[row.station_id] = s + lapse * (row.elev_m - target_elev_m)
        weights[row.station_id] = 1.0 / max(row.dist_km, 0.5) ** p
    if not cols:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(cols)
    w = pd.Series(weights)[frame.columns]
    wmat = frame.notna().mul(w, axis=1)
    est = (frame.fillna(0).mul(w, axis=1)).sum(axis=1) / wmat.sum(axis=1)
    return est.where(wmat.sum(axis=1) > 0)


def leave_one_out(stations: pd.DataFrame, hourly: dict[str, pd.Series], station_id: str,
                  summarize_fn, lapse_f_per_m: float | None = None) -> dict:
    """Hide one station, estimate it from its neighbors, compare.

    Returns hourly error and season-total error for each chill model.
    Run with lapse_f_per_m=0 too: that's the 'no elevation adjustment' comparison.
    """
    target = stations.set_index("station_id").loc[station_id]
    neigh = nearest(stations, target.lat, target.lon, config.NEIGHBORS, exclude=[station_id])
    est = estimate_series(hourly, neigh, target.elev_m, lapse_f_per_m)
    actual = hourly[station_id]
    both = pd.concat([actual.rename("actual"), est.rename("est")], axis=1).dropna()
    err = both["est"] - both["actual"]
    a, e = summarize_fn(both["actual"]), summarize_fn(both["est"])
    return {
        "station_id": station_id,
        "neighbors": neigh[["station_id", "dist_km"]].round(1).to_dict("records"),
        "hours_compared": int(len(both)),
        "hourly_bias_F": round(float(err.mean()), 2),
        "hourly_rmse_F": round(float(np.sqrt((err ** 2).mean())), 2),
        "actual": a,
        "estimated": e,
        "error": {k: round(e[k] - a[k], 1) for k in ("chill_hours", "utah_units", "chill_portions", "gdd")},
    }
