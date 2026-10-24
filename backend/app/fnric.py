"""FNRIC daily chill history: one CSV per station, downloaded once and kept in data/cache/.  Owner: Backend B.

FNRIC's weather models API (UC Davis Fruit & Nut Research & Information Center) is public and needs no
key, but it runs on a small paid budget. So:
- every function reads the cache by default and never downloads (download=False);
- only a one-off script passes download=True, one station at a time, with a pause;
- a station's file is saved only if it is real data, so a bad answer is never kept as if it were.

The CSV (endpoint chill-models-download) has one row per day: Date, hours_lt_45, hours_32_45,
units_utah, portions_dynamic. Values are daily amounts, not running totals, and rows are not sorted.
A day with no data is either absent, a row of empty values, or a row of exactly 0 in all four columns
(see has_data); all three count as missing days, never as 0 chill. The CSV has no count of hours with data per day (only the per-season JSON endpoint has
n_hours), so a day with some missing hours looks like a complete day; only whole missing days show.
Reference: github.com/ucdavis/fnric-reboot-the-eath-hackathon (cheat sheet and openapi.yaml).
"""
from __future__ import annotations

import io
import json
import os
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from . import config
from .data import _parse_decimal

BASE = "https://f5dby14cj5.execute-api.us-west-2.amazonaws.com/prod"
COLUMNS = ["hours_lt_45", "hours_32_45", "units_utah", "portions_dynamic"]


def fnric_id(station_id: str) -> str:
    """FNRIC's id for a station: our CIMIS number "6" becomes "CIMIS-6"; FNRIC ids pass through."""
    return station_id if "-" in station_id else f"CIMIS-{station_id}"


def cache_path(station_id: str) -> Path:
    """Where a station's daily chill CSV is kept, e.g. data/cache/fnric_CIMIS-6.csv."""
    return config.CACHE_DIR / f"fnric_{fnric_id(station_id)}.csv"


def is_cached(station_id: str) -> bool:
    """True if this station's FNRIC history is already saved (no request needed)."""
    return cache_path(station_id).exists()


def _empty() -> pd.DataFrame:
    """A daily-chill table with no rows, but the right columns."""
    return pd.DataFrame({"Date": pd.Series(dtype="datetime64[ns]"), **{c: pd.Series(dtype=float) for c in COLUMNS}})


def _parse(text: str) -> pd.DataFrame:
    """Daily chill rows from FNRIC's CSV text, sorted by date. Raises if it isn't real data."""
    daily = pd.read_csv(io.StringIO(text))
    missing = [c for c in ["Date", *COLUMNS] if c not in daily.columns]
    if missing or not daily[COLUMNS].notna().all(axis=1).any():
        raise ValueError(f"FNRIC sent no daily chill data (missing columns {missing}, {len(daily)} rows)")
    daily["Date"] = pd.to_datetime(daily["Date"])
    daily[COLUMNS] = daily[COLUMNS].astype(float)
    return daily[["Date", *COLUMNS]].sort_values("Date").reset_index(drop=True)


def _save(path: Path, text: str) -> None:
    """Write the file in one step (temporary file, then rename), so a stopped run never leaves half a file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def daily_chill(station_id: str, download: bool = False) -> pd.DataFrame:
    """A station's whole daily chill history (Date plus COLUMNS), oldest first.

    Reads the saved CSV. If it isn't saved: returns an empty table, or with download=True asks FNRIC
    once, checks the answer is real data, saves it, and returns it.
    """
    path = cache_path(station_id)
    if path.exists():
        return _parse(path.read_text())
    if not download:
        return _empty()
    r = requests.get(f"{BASE}/chill-models-download", params={"station-id": fnric_id(station_id)}, timeout=120)
    r.raise_for_status()
    daily = _parse(r.text)   # raises before saving if the answer isn't data
    _save(path, r.text)
    return daily


def has_data(rows: pd.DataFrame) -> pd.Series:
    """True for each row that is a real day of data: every value present, and not all four exactly 0.

    Why all-zero rows are gaps (DECISION FOR ADA, not a tuned threshold): FNRIC's daily files have winter
    runs of about two months where all four values are exactly 0 while CIMIS shows chill at the same
    station (Delano 182: Nov 7 to Dec 31, 2017; Belridge 146: Jan 7 to Mar 7, 2019). A real day can hardly
    be all zeros: Utah units go negative for warm hours (about a third of Sept-Mar days in these files have
    negative Utah units), so 0 hours at or below 45F and also exactly 0 Utah units needs every hour to sit
    in Utah's 0-weight bands. In the 19 saved files, days with 0 hours at or below 45F and 0 Utah units but
    some portions happen at most 8 times per station in 40 years, while all-zero rows fall mostly in
    Nov-Feb, when chill is surest. A rare real all-zero day may be counted as missing; that is the safe
    side, because a missing day is reported (days_missing), never filled.
    """
    present = rows[COLUMNS].notna().all(axis=1)
    all_zero = (rows[COLUMNS] == 0).all(axis=1)
    return present & ~all_zero


def complete_days(daily: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """The rows from start to end (both included) that are real days of data (see has_data)."""
    window = daily[(daily["Date"] >= pd.Timestamp(start)) & (daily["Date"] <= pd.Timestamp(end))]
    return window[has_data(window)]


def daily_series(daily: pd.DataFrame, start: date, end: date, column: str = "portions_dynamic") -> pd.Series:
    """One daily amount from start to end, indexed by date, days with data only (missing days are absent)."""
    rows = complete_days(daily, start, end)
    return pd.Series(rows[column].to_numpy(), index=pd.DatetimeIndex(rows["Date"]), name=column)


def season_totals(daily: pd.DataFrame, start: date, end: date) -> dict:
    """Sum of each daily amount from start to end (both included), over the days with data.

    days: days with data. days_missing: the other days of the window (no row, empty values, or all zeros).
    """
    complete = complete_days(daily, start, end)
    days_in_window = (end - start).days + 1
    return {"days": int(len(complete)), "days_missing": days_in_window - int(len(complete)),
            **{c: float(complete[c].sum()) for c in COLUMNS}}


def stations(download: bool = False) -> pd.DataFrame:
    """FNRIC's station list: station_id (FNRIC form), name, county, lat, lon, active.

    Saved as data/cache/fnric_stations.json. Not saved and download=False: an empty table.
    """
    path = config.CACHE_DIR / "fnric_stations.json"
    if path.exists():
        raw = json.loads(path.read_text())
    elif download:
        r = requests.get(f"{BASE}/stations", timeout=60)
        r.raise_for_status()
        raw = r.json()
        if not raw.get("stations"):
            raise ValueError("FNRIC sent no stations")
        _save(path, json.dumps(raw))
    else:
        return pd.DataFrame(columns=["station_id", "name", "county", "lat", "lon", "active"])
    return pd.DataFrame([{
        "station_id": s["StationID"], "name": s.get("Name"), "county": s.get("County"),
        "lat": _parse_decimal(s.get("HmsLatitude")), "lon": _parse_decimal(s.get("HmsLongitude")),
        "active": str(s.get("IsActive")).lower() == "true",
    } for s in raw["stations"]])
