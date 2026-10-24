"""Estimate hourly temperature at any point, and measure how good the estimate is.

Method (v1): inverse-distance weighting of nearby stations after moving each station's
temperature to the target's elevation with a lapse rate. Swap in regression kriging
(PyKrige) later if it validates better; validate.py is the judge.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import requests

from . import config


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


ELEVATION_CACHE = config.CACHE_DIR / "elevations.json"


def elevation_m(lat: float, lon: float) -> float | None:
    """Terrain height from the Open-Meteo Elevation API (Copernicus 90 m). None if offline.

    Each answer is saved in data/cache/elevations.json, so a pin looked up once keeps the same
    elevation with Wi-Fi off. Without this, an offline demo would fall back to the nearest
    station's elevation and show different numbers than the online one.
    """
    key = f"{lat:.4f},{lon:.4f}"
    try:
        saved = json.loads(ELEVATION_CACHE.read_text()) if ELEVATION_CACHE.exists() else {}
    except ValueError:
        saved = {}  # a damaged cache file is ignored and rewritten
    if key in saved:
        return float(saved[key])
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude": lat, "longitude": lon}, timeout=10)
        r.raise_for_status()
        elev = float(r.json()["elevation"][0])
    except Exception:
        return None
    saved[key] = elev
    ELEVATION_CACHE.write_text(json.dumps(saved, indent=1))
    return elev


def pin_elevation(stations: pd.DataFrame, lat: float, lon: float) -> tuple[float, str]:
    """Elevation of a pin and where it came from. Falls back to the nearest station when offline."""
    elev = elevation_m(lat, lon)
    if elev is not None:
        return elev, "open-meteo"
    st = nearest(stations, lat, lon, 1)
    return float(st["elev_m"].iloc[0]), "nearest station (offline)"


def nearest(stations: pd.DataFrame, lat: float, lon: float, k: int, exclude=()) -> pd.DataFrame:
    """The k stations closest to a point, with a dist_km column, closest first."""
    s = stations[~stations["station_id"].isin(exclude)].copy()
    s["dist_km"] = haversine_km(lat, lon, s["lat"].to_numpy(), s["lon"].to_numpy())
    return s.nsmallest(k, "dist_km")


def candidates(stations: pd.DataFrame, lat: float, lon: float, target_elev_m: float,
               exclude=()) -> pd.DataFrame:
    """Every station that may be a neighbor of this point, closest first.

    This is the one station pool for the whole project: the app picks neighbors from it and
    scripts/warm_cache.py caches it, so the demo never asks for a station that wasn't cached.
    Closed stations stay in the pool on purpose: their old data helps estimate past winters.
    A station is left out if it is farther than config.MAX_NEIGHBOR_KM, or if its elevation
    differs from the point's by more than config.MAX_ELEV_DIFF_M (for example a station across
    the Coast Range, whose winters are not like the valley floor's).
    """
    s = stations[~stations["station_id"].isin(exclude)].copy()
    s["dist_km"] = haversine_km(lat, lon, s["lat"].to_numpy(), s["lon"].to_numpy())
    s = s[s["dist_km"] <= config.MAX_NEIGHBOR_KM]
    s = s[(s["elev_m"] - target_elev_m).abs() <= config.MAX_ELEV_DIFF_M]
    return s.nsmallest(config.NEIGHBOR_CANDIDATES, "dist_km")


def coverage(series: pd.Series | None, start, end) -> float:
    """Share of the hours from start to end (whole days, inclusive) that have a temperature."""
    if series is None or series.empty:
        return 0.0
    hours = ((pd.Timestamp(end) - pd.Timestamp(start)).days + 1) * 24
    lo, hi = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)
    inside = series[(series.index >= lo) & (series.index < hi)]
    return float(inside.notna().sum()) / hours if hours > 0 else 0.0


def pick_neighbors(hourly: dict[str, pd.Series], cands: pd.DataFrame, start, end,
                   k: int | None = None) -> pd.DataFrame:
    """The k closest candidates that actually have data for this window.

    A station counts only if it has a temperature for at least config.MIN_NEIGHBOR_COVERAGE
    of the window's hours. So a station that closed, or opened after this winter, is skipped
    and the next closest one takes its place, instead of the estimate quietly shrinking to
    two or three stations. Shorter gaps inside a station that counts are handled hour by hour
    in estimate_series.
    """
    k = config.NEIGHBORS if k is None else k
    keep = [sid for sid in cands["station_id"]
            if coverage(hourly.get(sid), start, end) >= config.MIN_NEIGHBOR_COVERAGE]
    return cands[cands["station_id"].isin(keep[:k])]


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
                  summarize_fn, lapse_f_per_m: float | None = None,
                  neighbors: pd.DataFrame | None = None) -> dict:
    """Hide one station, estimate it from its neighbors, compare.

    Returns hourly error and season-total error for each chill model.
    Run with lapse_f_per_m=0 too: that's the 'no elevation adjustment' comparison.
    neighbors: the stations to estimate from. If not given, they are picked the same way the
    app picks them (candidates around the hidden station that have data in `hourly`).
    """
    target = stations.set_index("station_id").loc[station_id]
    actual = hourly[station_id]
    if neighbors is None:
        cands = candidates(stations, target.lat, target.lon, target.elev_m, exclude=[station_id])
        neighbors = pick_neighbors(hourly, cands, actual.index.min(), actual.index.max())
    neigh = neighbors
    est = estimate_series(hourly, neigh, target.elev_m, lapse_f_per_m)
    both = pd.concat([actual.rename("actual"), est.rename("est")], axis=1).dropna()
    err = both["est"] - both["actual"]
    a, e = summarize_fn(both["actual"]), summarize_fn(both["est"])
    return {
        "station_id": station_id,
        # the stations actually used, so the proof sentence names real neighbors
        "neighbors": neigh[["station_id", "name", "dist_km", "elev_m"]].round(1).to_dict("records"),
        "hours_compared": int(len(both)),
        "hourly_bias_F": round(float(err.mean()), 2),
        "hourly_rmse_F": round(float(np.sqrt((err ** 2).mean())), 2),
        "actual": a,
        "estimated": e,
        "error": {k: round(e[k] - a[k], 1) for k in ("chill_hours", "utah_units", "chill_portions", "gdd")},
    }
