"""Station data: CIMIS (real) or synthetic (for building before real data lands).

Every function returns the team's data contract:
    station_id, lat, lon, elev_m, datetime, temp_F, source, is_filled
"""
from __future__ import annotations

import re
import zlib
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

from . import config

CIMIS_BASE = "https://et.water.ca.gov/api"          # legacy API: still serves the station list
CIMIS_DATA_URL = "https://et.water.ca.gov/StationWeb/GetDataByStationNumber"  # New CIMIS weather data
# TODO(Saliha): if StationWeb/GetAllStations returns the same fields as /api/station
# (StationNbr, Name, County, HmsLatitude, HmsLongitude, Elevation, IsActive), switch get_stations to it.
CONTRACT = ["station_id", "lat", "lon", "elev_m", "datetime", "temp_F", "source", "is_filled"]


# ---------------------------------------------------------------- stations

def _parse_decimal(hms: str) -> float:
    """CIMIS gives coordinates like "38º32'7N / 38.5353"; take the decimal part."""
    m = re.search(r"/\s*(-?\d+\.\d+)", str(hms))
    return float(m.group(1)) if m else float("nan")


def get_stations() -> pd.DataFrame:
    """Columns: station_id, name, county, lat, lon, elev_m, active."""
    if config.DATA_SOURCE == "synthetic":
        return _synthetic_stations()
    cache = config.CACHE_DIR / "stations.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    r = requests.get(f"{CIMIS_BASE}/station", headers={"Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    rows = []
    for s in r.json()["Stations"]:
        rows.append({
            "station_id": str(s["StationNbr"]),
            "name": s.get("Name"),
            "county": s.get("County"),
            "lat": _parse_decimal(s.get("HmsLatitude")),
            "lon": _parse_decimal(s.get("HmsLongitude")),
            "elev_m": float(s.get("Elevation") or 0) * 0.3048,  # CIMIS reports feet
            "active": str(s.get("IsActive")).lower() == "true",
        })
    df = pd.DataFrame(rows)
    df.to_parquet(cache)
    return df


# ---------------------------------------------------------------- hourly data

def season_year(d: date) -> int:
    """Chill seasons run Sept 1 to Aug 31; a season is named by the year it starts."""
    return d.year if d.month >= 9 else d.year - 1


def get_hourly(station_id: str, start: date, end: date) -> pd.DataFrame:
    """Hourly air temperature for one station between start and end (inclusive).

    Cached as one file per station per season (Sept 1 to Aug 31), the size CIMIS accepts in
    one request. Any window is then sliced from those files, so endpoints asking for slightly
    different dates never trigger new downloads. The current season's file is refreshed once
    a day, because it is still growing.
    """
    frames = [season_hourly(station_id, y) for y in range(season_year(start), season_year(end) + 1)]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=CONTRACT)
    df = pd.concat(frames, ignore_index=True)
    lo, hi = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)
    return df[(df["datetime"] >= lo) & (df["datetime"] < hi)].reset_index(drop=True)


def season_hourly(station_id: str, year: int) -> pd.DataFrame:
    """One station, one whole season, from cache or one download."""
    s_start = date(year, 9, 1)
    s_end = min(date(year + 1, 8, 31), date.today() - timedelta(days=1))
    if s_end < s_start:
        return pd.DataFrame(columns=CONTRACT)
    current = s_end < date(year + 1, 8, 31)
    cache = config.CACHE_DIR / f"hourly_{config.DATA_SOURCE}_{station_id}_{year}.parquet"
    if cache.exists():
        fresh = (date.today() - date.fromtimestamp(cache.stat().st_mtime)).days < 1
        if not current or fresh:
            return pd.read_parquet(cache)
    if config.DATA_SOURCE == "synthetic":
        df = _synthetic_hourly(station_id, s_start, s_end)
    else:
        df = _cimis_hourly(station_id, s_start, s_end)
    df = fill_gaps(df)
    df.to_parquet(cache)
    return df


class CimisVolumeError(Exception):
    """CIMIS refused the request as too large (ERR2112 DATA VOLUME VIOLATION)."""


def _cimis_request(station_id: str, start: date, end: date) -> list[dict]:
    """One New CIMIS request for hourly air temperature. Returns the raw records.

    New CIMIS (cimis.water.ca.gov, Web API > REST API) changed two things from the legacy API:
    the address (StationWeb/GetDataByStationNumber with stationNbrs and isHourly), and the key,
    which now goes in the Ocp-Apim-Subscription-Key header instead of the URL. The response
    shape (Data > Providers > Records) is unchanged.
    """
    params = {"stationNbrs": station_id, "startDate": str(start), "endDate": str(end),
              "isHourly": "true", "dataItems": "hly-air-tmp", "unitOfMeasure": "E"}
    headers = {"Accept": "application/json", "Ocp-Apim-Subscription-Key": config.CIMIS_APP_KEY}
    r = requests.get(CIMIS_DATA_URL, params=params, headers=headers, timeout=120)
    if "ERR2112" in r.text:
        raise CimisVolumeError(f"{station_id} {start}..{end}")
    if not r.headers.get("Content-Type", "").startswith("application/json"):
        raise RuntimeError(f"CIMIS sent back {r.headers.get('Content-Type')} instead of data "
                           f"(status {r.status_code}). Check the key and CIMIS_DATA_URL.")
    if r.status_code != 200:
        raise RuntimeError(f"CIMIS error {r.status_code}: {r.text[:200]}")
    records = []
    for provider in r.json()["Data"]["Providers"]:
        records.extend(provider.get("Records", []))
    return records


def _cimis_records(station_id: str, start: date, end: date) -> list[dict]:
    """Records for any window. If CIMIS says the window is too large, split it in half and retry.

    So a whole season goes in one request when CIMIS allows it, and in as few pieces as needed
    when it doesn't.
    """
    try:
        return _cimis_request(station_id, start, end)
    except CimisVolumeError:
        if start >= end:
            raise
        mid = start + (end - start) // 2
        return _cimis_records(station_id, start, mid) + _cimis_records(station_id, mid + timedelta(days=1), end)


def _cimis_hourly(station_id: str, start: date, end: date) -> pd.DataFrame:
    """Hourly air temperature for one station as the data contract table."""
    if not config.CIMIS_APP_KEY:
        raise RuntimeError("Set CIMIS_APP_KEY in .env, or use DATA_SOURCE=synthetic")
    records = _cimis_records(station_id, start, end)
    st = get_stations().set_index("station_id").loc[station_id]
    rows = []
    for rec in records:
        hour = int(rec["Hour"]) // 100  # "0100".."2400", hour ending
        ts = pd.Timestamp(rec["Date"]) + pd.Timedelta(hours=hour)
        val = (rec.get("HlyAirTmp") or {}).get("Value")
        rows.append({"datetime": ts, "temp_F": float(val) if val not in (None, "") else np.nan})
    if not rows:  # e.g. an inactive station after it closed
        return pd.DataFrame(columns=CONTRACT)
    df = pd.DataFrame(rows)
    df["station_id"], df["lat"], df["lon"], df["elev_m"] = station_id, st.lat, st.lon, st.elev_m
    df["source"], df["is_filled"] = "cimis", False
    return df[CONTRACT]


def fill_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """Put every hour on the clock; fill gaps <= MAX_FILL_HOURS, flag what was filled."""
    if df.empty:
        return df
    meta = df.iloc[0][["station_id", "lat", "lon", "elev_m", "source"]]
    s = df.set_index("datetime")["temp_F"].sort_index()
    s = s[~s.index.duplicated()]
    full = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="h"))
    filled = full.interpolate(limit=config.MAX_FILL_HOURS, limit_area="inside")
    out = pd.DataFrame({"datetime": full.index, "temp_F": filled.to_numpy(),
                        "is_filled": (full.isna() & filled.notna()).to_numpy()})
    for k, v in meta.items():
        out[k] = v
    return out[CONTRACT]


# ---------------------------------------------------------------- synthetic data
# Clearly fake. Lets the frontend and the validation code run before CIMIS data lands.

_SYN = [  # station_id, name, county, lat, lon, elev_m  (approximate locations)
    ("6", "Davis", "Yolo", 38.535, -121.776, 18),
    ("12", "Durham (inactive)", "Butte", 39.609, -121.824, 40),
    ("70", "Manteca", "San Joaquin", 37.834, -121.223, 10),
    ("71", "Modesto", "Stanislaus", 37.645, -121.188, 11),
    ("39", "Parlier", "Fresno", 36.598, -119.504, 103),
    ("5", "Shafter", "Kern", 35.532, -119.282, 110),
    ("SYN-A", "Synthetic Orland", "Glenn", 39.75, -122.15, 75),
    ("SYN-B", "Synthetic Biggs", "Butte", 39.42, -121.71, 30),
    ("SYN-C", "Synthetic Colusa", "Colusa", 39.23, -122.02, 18),
    ("SYN-D", "Synthetic Foothill", "Placer", 38.95, -121.10, 450),
    ("SYN-E", "Synthetic Lost Hills", "Kern", 35.62, -119.69, 85),
    ("SYN-F", "Synthetic Delano", "Kern", 35.77, -119.25, 95),
    ("SYN-G", "Synthetic Arvin", "Kern", 35.21, -118.83, 150),
    ("SYN-H", "Synthetic Kettleman", "Kings", 36.00, -119.96, 120),
]


def _synthetic_stations() -> pd.DataFrame:
    df = pd.DataFrame(_SYN, columns=["station_id", "name", "county", "lat", "lon", "elev_m"])
    df["active"] = df["station_id"] != "12"
    return df


def synthetic_temp(lat, lon, elev_m, index: pd.DatetimeIndex, seed: int = 0) -> np.ndarray:
    """Seasonal + daily cycle + latitude/elevation effects + shared weather + local noise."""
    doy = index.dayofyear.to_numpy()
    hour = index.hour.to_numpy()
    seasonal = 61 - 16 * np.cos(2 * np.pi * (doy - 15) / 365.25)
    daily = 11 * np.sin(2 * np.pi * (hour - 9) / 24)
    days = (index - pd.Timestamp("2000-01-01")).days.to_numpy()  # same weather at every station
    shared = 5 * np.sin(days / 4.3) + 3 * np.sin(days / 9.7)      # regional weather systems
    local = np.random.default_rng(seed).normal(0, 1.2, len(index))
    return seasonal + daily + shared + local - 1.2 * (lat - 38.5) - config.LAPSE_F_PER_M * elev_m


def _synthetic_hourly(station_id: str, start: date, end: date) -> pd.DataFrame:
    st = _synthetic_stations().set_index("station_id").loc[station_id]
    idx = pd.date_range(pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(hours=23), freq="h")
    seed = zlib.crc32(station_id.encode()) % 10_000  # deterministic across runs
    temps = synthetic_temp(st.lat, st.lon, st.elev_m, idx, seed=seed)
    temps[np.random.default_rng(seed).random(len(temps)) < 0.01] = np.nan  # ~1% missing
    return pd.DataFrame({
        "station_id": station_id, "lat": st.lat, "lon": st.lon, "elev_m": st.elev_m,
        "datetime": idx, "temp_F": temps, "source": "synthetic", "is_filled": False,
    })[CONTRACT]
