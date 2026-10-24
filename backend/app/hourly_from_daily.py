"""Hourly temperatures rebuilt from daily highs and lows (Julia Stover's ask).

Many weather records only keep each day's high and low. Chill models need hours, so this module
rebuilds an hourly curve from the daily values, the way FNRIC's reference tool chillR does it:
a sine curve from sunrise to sunset, then a logarithmic cool-down through the night to the next
morning's low, with sunrise and sunset worked out from latitude and the day of the year.

Ported line by line from chillR 0.77 (Eike Luedeling; CRAN mirror github.com/cran/chillR):
    R/daylength.R          function daylength()          -> daylength() here
    R/make_hourly_temps.R  function make_hourly_temps()  -> make_hourly_temps() here
References in chillR: Linvill DE (1990) HortScience 25(1):14-16 (the temperature curve); Spencer JW
(1971) Search 2(5):172 and Almorox J et al. (2005) Energy Conversion and Management 46:1465-1471
(sunrise, sunset and day length).

Two deliberate differences from chillR, both about missing data (CLAUDE.md: never fill silently):
1. chillR drops days with a missing high or low and then joins the days on either side, so a night
   after a gap is drawn toward a low from days later. Here a missing day gives 24 missing hours, and
   the night hours of its neighbors that would need it are missing too.
2. chillR fills the first day's early morning and the last day's evening (which have no neighbor day)
   with that day's low. Here they stay missing. Give one extra day on each side to avoid them.

Hours are chillR's Hour_0 ... Hour_23 of each date, in solar time (noon is 12:00; chillR makes no
time-zone or longitude correction, and neither do we). Rows wrapped for the data contract are tagged
source="daily" and is_filled=False.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CONTRACT = ["station_id", "lat", "lon", "elev_m", "datetime", "temp_F", "source", "is_filled"]
HOURS = np.arange(24)


def daylength(latitude: float, jday) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sunrise, sunset (hours, solar time) and day length (hours) for each day of the year.

    Port of chillR R/daylength.R, daylength(): solar declination from Spencer (1971), sunrise at a sun
    elevation of -0.8333 degrees (Almorox et al. 2005). Polar nights give sunrise = sunset = -99 and
    day length 0; polar days give 99, 99 and 24, exactly as chillR does.
    """
    jday = np.asarray(jday, dtype=float)
    gamma = 2 * np.pi / 365 * (jday - 1)
    delta = 180 / np.pi * (0.006918 - 0.399912 * np.cos(gamma) + 0.070257 * np.sin(gamma)
                           - 0.006758 * np.cos(2 * gamma) + 0.000907 * np.sin(2 * gamma)
                           - 0.002697 * np.cos(3 * gamma) + 0.00148 * np.sin(3 * gamma))
    cos_wo = ((np.sin(-0.8333 / 360 * 2 * np.pi) - np.sin(latitude / 360 * 2 * np.pi)
               * np.sin(delta / 360 * 2 * np.pi))
              / (np.cos(latitude / 360 * 2 * np.pi) * np.cos(delta / 360 * 2 * np.pi)))
    normal = (cos_wo >= -1) & (cos_wo <= 1)
    half_day = np.arccos(np.clip(cos_wo, -1, 1)) / (15 / 360 * 2 * np.pi)
    sunrise = np.where(normal, 12 - half_day, -99.0)
    sunset = np.where(normal, 12 + half_day, -99.0)
    length = sunset - sunrise
    length = np.where(cos_wo > 1, 0.0, length)
    length = np.where(cos_wo < -1, 24.0, length)
    sunrise = np.where(length == 24, 99.0, sunrise)
    sunset = np.where(length == 24, 99.0, sunset)
    return sunrise, sunset, length


def _sun_times(latitude: float, jday: np.ndarray) -> dict:
    """Sunrise, sunset and day length for each day, plus the previous sunset and the next sunrise.

    As in make_hourly_temps.R: day length for the day before the first and after the last, and
    polar codes replaced (sunrise 99 -> 0, -99 -> 12; sunset 99 -> 24, -99 -> 12).
    """
    days = np.concatenate([[jday[0] - 1], jday, [jday[-1] + 1]])
    sunrise, sunset, length = daylength(latitude, days)
    sunrise = np.select([sunrise == 99, sunrise == -99], [0.0, 12.0], sunrise)
    sunset = np.select([sunset == 99, sunset == -99], [24.0, 12.0], sunset)
    return {"sunrise": sunrise[1:-1], "sunset": sunset[1:-1], "length": length[1:-1],
            "prev_sunset": sunset[:-2], "next_sunrise": sunrise[2:]}


def _full_days(daily: pd.DataFrame) -> pd.DataFrame:
    """Daily table on every calendar date from first to last; dates not given are missing."""
    daily = daily[["tmin_F", "tmax_F"]].astype(float).sort_index()
    daily.index = pd.DatetimeIndex(daily.index).normalize()
    return daily.reindex(pd.date_range(daily.index.min(), daily.index.max(), freq="D"))


def _hour_grid(tmin, tmax, sun: dict) -> np.ndarray:
    """Temperatures for every day (rows) and hour 0-23 (columns), make_hourly_temps.R's hour loop.

    Neighbor values (previous high/low, next low) come from the adjacent calendar day, so a missing
    neighbor gives missing night hours instead of chillR's jump over the gap.
    """
    prev_max, prev_min = np.r_[np.nan, tmax[:-1]], np.r_[np.nan, tmin[:-1]]
    next_min = np.r_[tmin[1:], np.nan]
    sunrise, sunset, length = sun["sunrise"], sun["sunset"], sun["length"]
    prev_sunset, next_sunrise = sun["prev_sunset"], sun["next_sunrise"]
    t_sunset = tmin + (tmax - tmin) * np.sin(np.pi * (sunset - sunrise) / (length + 4))
    prev_t_sunset = prev_min + (prev_max - prev_min) * np.sin(np.pi * length / (length + 4))

    col = lambda a: np.asarray(a, dtype=float)[:, None]  # noqa: E731  one value per day, as a column
    h = HOURS[None, :]
    # polar day or night: the day's mean (chillR's no_riseset), later overwritten where a branch applies
    grid = np.where(np.isin(col(length), [0, 24, -99]), col((tmax + tmin) / 2), np.nan) * np.ones((1, 24))
    morning = h <= col(sunrise)
    daytime = (h > col(sunrise)) & (h <= col(sunset))
    evening = h >= col(sunset)
    with np.errstate(invalid="ignore", divide="ignore"):
        night_before = (col(prev_t_sunset)
                        - (col(prev_t_sunset) - col(tmin))
                        / np.log(np.maximum(1, 24 - (col(prev_sunset) - col(sunrise))))
                        * np.log(h + 24 - col(prev_sunset) + 1))
        day_curve = col(tmin) + (col(tmax) - col(tmin)) * np.sin(np.pi * (h - col(sunrise)) / (col(length) + 4))
        night_after = (col(t_sunset)
                       - (col(t_sunset) - col(next_min))
                       / np.log(24 - (col(sunset) - col(next_sunrise)) + 1)
                       * np.log(h - col(sunset) + 1))
    grid = np.where(morning, night_before, grid)
    grid = np.where(daytime, day_curve, grid)
    return np.where(evening, night_after, grid)   # chillR assigns evening last, so it wins at h == sunset


def make_hourly_temps(daily: pd.DataFrame, latitude: float) -> pd.Series:
    """Hourly °F rebuilt from daily highs and lows (port of chillR make_hourly_temps, Linvill 1990).

    daily: one row per date (DatetimeIndex), columns tmin_F and tmax_F in °F. Dates in between that are
    absent, or have a missing value, give missing hours.
    latitude: decimal degrees of the place (sets sunrise and sunset).
    Returns a Series named temp_F indexed by date + hour (00:00 ... 23:00 of every date).
    """
    days = _full_days(daily)
    if days.empty:
        return pd.Series(dtype=float, name="temp_F")
    sun = _sun_times(latitude, days.index.dayofyear.to_numpy())
    grid = _hour_grid(days["tmin_F"].to_numpy(), days["tmax_F"].to_numpy(), sun)
    index = (days.index.repeat(24) + pd.to_timedelta(np.tile(HOURS, len(days)), unit="h"))
    return pd.Series(grid.ravel(), index=index, name="temp_F")


def daily_min_max(hourly: pd.Series) -> pd.DataFrame:
    """Each day's low and high (tmin_F, tmax_F) from an hourly °F series labeled by hour ending.

    CIMIS labels hours by when they end (01:00 ... 24:00, the last one stamped 00:00 next day), so an
    hour is assigned to the day it started in. A day with any hour missing gets no low or high: a
    partial day could miss the real low, so it is left missing rather than guessed.
    """
    day = (hourly.index - pd.Timedelta(hours=1)).normalize()
    grouped = hourly.groupby(day)
    out = pd.DataFrame({"tmin_F": grouped.min(), "tmax_F": grouped.max()})
    whole = grouped.count() == 24
    return out.where(whole)


def to_contract(hourly: pd.Series, station_id: str, lat: float, lon: float, elev_m: float) -> pd.DataFrame:
    """Rebuilt hours as the team's data contract table: source "daily", is_filled False."""
    return pd.DataFrame({
        "station_id": station_id, "lat": lat, "lon": lon, "elev_m": elev_m,
        "datetime": hourly.index, "temp_F": hourly.to_numpy(),
        "source": "daily", "is_filled": False,
    })[CONTRACT]
