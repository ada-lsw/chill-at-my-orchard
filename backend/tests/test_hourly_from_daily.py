"""Hourly temperatures rebuilt from daily highs and lows (port of chillR's make_hourly_temps).

The formulas come from chillR 0.77 (github.com/cran/chillR): R/make_hourly_temps.R and R/daylength.R.

What "the hourly max and min match the daily inputs" means for this formula (Linvill 1990 as coded in
chillR):
- Daytime is a sine curve that peaks exactly at 2pm (sunrise + half of daylength + 4 hours), so the
  2pm hour equals the day's high exactly.
- Night is a log decay from the previous sunset toward the morning low. chillR's morning formula has a
  "+1" in the top log but not the bottom one, so the last hour before sunrise dips slightly BELOW the
  day's low: by at most (sunset temp - low) * (ln(N+1)/ln(N) - 1), N = hours from sunset to sunrise.
  With California winter nights (N about 14 h) that is under 3% of the day's range (0.36°F on a
  35-55°F day at Davis, worked out below). We test within 3%.
- The evening of each day decays toward the NEXT day's low, and the early morning starts from the
  PREVIOUS day's sunset temperature. So on a day when the weather changes a lot, a night hour can sit
  outside that day's own high and low. With steady weather (the first test), it never does.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app import hourly_from_daily as hfd


def daily_table(start: str, tmins: list, tmaxs: list) -> pd.DataFrame:
    """Daily min/max °F indexed by date, the module's input shape."""
    idx = pd.date_range(start, periods=len(tmins), freq="D")
    return pd.DataFrame({"tmin_F": tmins, "tmax_F": tmaxs}, index=idx)


def by_day(hourly: pd.Series) -> pd.core.groupby.SeriesGroupBy:
    """Hourly values grouped by calendar day (hours 0 to 23)."""
    return hourly.groupby(hourly.index.normalize())


def test_steady_weather_hourly_max_and_min_match_daily():
    """Same high and low every day: each inner day's hourly max is the high, its min is the low (within 3% of range)."""
    daily = daily_table("2025-01-10", [35.0] * 7, [55.0] * 7)
    hourly = hfd.make_hourly_temps(daily, latitude=38.5)
    assert len(hourly) == 7 * 24
    inner = by_day(hourly).agg(["max", "min"]).iloc[1:-1]   # first/last day lack a neighbor day
    rng = 55.0 - 35.0
    assert np.allclose(inner["max"], 55.0, atol=1e-9)
    assert (inner["min"] <= 35.0).all() and (inner["min"] >= 35.0 - 0.03 * rng).all()


def test_changing_weather_2pm_is_the_high_and_sunrise_is_near_the_low():
    """Different every day: 2pm equals that day's high; the hour before sunrise is within 3% of the low."""
    tmins = [30.0, 41.0, 36.0, 28.0, 45.0, 39.0]
    tmaxs = [52.0, 60.0, 49.0, 58.0, 66.0, 50.0]
    daily = daily_table("2024-12-01", tmins, tmaxs)
    hourly = hfd.make_hourly_temps(daily, latitude=36.0)
    sunrise, _, _ = hfd.daylength(36.0, daily.index.dayofyear.to_numpy())
    for i, day in enumerate(daily.index):
        assert hourly[day + pd.Timedelta(hours=14)] == pytest.approx(tmaxs[i], abs=1e-9)
        if 0 < i:   # day 1 has no previous evening to start its night from
            before_sunrise = hourly[day + pd.Timedelta(hours=int(np.floor(sunrise[i])))]
            assert abs(before_sunrise - tmins[i]) <= 0.03 * (max(tmaxs[i - 1], tmaxs[i]) - tmins[i])


def test_daylength_at_equinox_is_about_12_hours():
    """Around Mar 20 (day 79-80) day length is ~12 h; chillR counts sunrise at -0.83° (refraction), so a bit over."""
    for lat in (0.0, 36.0, 39.6):
        _, _, length = hfd.daylength(lat, np.array([80]))
        assert length[0] == pytest.approx(12.0, abs=0.25)
    # winter is shorter than summer at California latitudes
    _, _, dec = hfd.daylength(38.5, np.array([355]))
    _, _, jun = hfd.daylength(38.5, np.array([172]))
    assert dec[0] < 10.0 < 14.0 < jun[0]


def test_missing_day_gives_missing_hours_never_filled():
    """A missing day is all missing; its neighbors lose only the night hours that would need it."""
    daily = daily_table("2025-01-10", [35.0, 36.0, np.nan, 34.0, 33.0], [55.0, 56.0, 57.0, 54.0, 53.0])
    hourly = hfd.make_hourly_temps(daily, latitude=38.5)
    missing_day = by_day(hourly).get_group(pd.Timestamp("2025-01-12"))
    assert missing_day.isna().all()
    before = by_day(hourly).get_group(pd.Timestamp("2025-01-11"))
    after = by_day(hourly).get_group(pd.Timestamp("2025-01-13"))
    assert before.iloc[:17].notna().all() and before.iloc[18:].isna().all()   # evening needs next low
    assert after.iloc[:8].isna().all() and after.iloc[8:].notna().all()       # morning needs last evening
    # the series edges have no neighbor day either: missing, not filled
    assert by_day(hourly).get_group(pd.Timestamp("2025-01-10")).iloc[:7].isna().all()
    assert by_day(hourly).get_group(pd.Timestamp("2025-01-14")).iloc[17:].isna().all()


def test_golden_values_by_hand_from_chillr_formulas():
    """Lat 38.5, Jan 15 2025 (day 15), steady 35/55°F. Worked by hand from daylength.R and make_hourly_temps.R.

    daylength.R, day 15: Gamma = 2*pi/365*14; declination = -21.2727°; CosWo = 0.289749;
      sunrise = 12 - acos(CosWo)/(15°) = 7.12286 h, sunset = 16.87714 h, daylength = 9.75427 h
      (days 14 and 16: sunset 16.86609, sunrise 7.11142).
    Tsunset = 35 + 20*sin(pi*9.75427/13.75427) = 50.83458 (prev_Tsunset is the same, steady weather).
    3am (night, morning branch):
      50.83458 - (50.83458-35)/log(24-(16.86609-7.12286)) * log(3+24-16.86609+1) = 36.47330
    noon (day branch): 35 + 20*sin(pi*(12-7.12286)/13.75427) = 52.94922
    8pm (night, evening branch):
      50.83458 - (50.83458-35)/log(24-(16.87714-7.11142)+1) * log(20-16.87714+1) = 42.59884
    """
    daily = daily_table("2025-01-14", [35.0] * 3, [55.0] * 3)
    hourly = hfd.make_hourly_temps(daily, latitude=38.5)
    sunrise, sunset, length = hfd.daylength(38.5, np.array([15]))
    assert (sunrise[0], sunset[0], length[0]) == pytest.approx((7.12286, 16.87714, 9.75427), abs=1e-5)
    day = pd.Timestamp("2025-01-15")
    assert hourly[day + pd.Timedelta(hours=3)] == pytest.approx(36.47330, abs=1e-4)
    assert hourly[day + pd.Timedelta(hours=12)] == pytest.approx(52.94922, abs=1e-4)
    assert hourly[day + pd.Timedelta(hours=20)] == pytest.approx(42.59884, abs=1e-4)


def test_contract_rows_are_tagged_daily_and_not_filled():
    """Wrapped as the team's data contract: source "daily", is_filled False, missing stays missing."""
    daily = daily_table("2025-01-10", [35.0, np.nan, 34.0], [55.0, 56.0, 54.0])
    hourly = hfd.make_hourly_temps(daily, latitude=38.5)
    df = hfd.to_contract(hourly, station_id="12", lat=39.6, lon=-121.8, elev_m=40.0)
    assert list(df.columns) == ["station_id", "lat", "lon", "elev_m", "datetime", "temp_F", "source", "is_filled"]
    assert (df["source"] == "daily").all() and not df["is_filled"].any()
    assert df["temp_F"].isna().sum() == hourly.isna().sum() > 0


def test_daily_min_max_from_hourly_uses_whole_days_only():
    """CIMIS hours are labeled by hour ending (01:00..24:00); a day with any missing hour gives no min/max."""
    idx = pd.date_range("2025-01-10 01:00", "2025-01-12 00:00", freq="h")   # hours ending Jan 10 and 11
    temps = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    temps.iloc[30] = np.nan                                                # one hour of Jan 11 missing
    daily = hfd.daily_min_max(temps)
    assert list(daily.index) == [pd.Timestamp("2025-01-10"), pd.Timestamp("2025-01-11")]
    assert (daily.loc["2025-01-10", "tmin_F"], daily.loc["2025-01-10", "tmax_F"]) == (0.0, 23.0)
    assert daily.loc["2025-01-11"].isna().all()


def test_daily_only_check_pitch_sentence_uses_typical_and_worst():
    """scripts/daily_only_check.py: typical = mean absolute difference, worst = largest absolute one."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "scripts" / "daily_only_check.py"
    spec = importlib.util.spec_from_file_location("daily_only_check", path)
    dc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dc)
    rows = [{"station": "12", "diff_chill_portions": 1.0}, {"station": "12", "diff_chill_portions": -3.0},
            {"station": "5", "diff_chill_portions": 2.0}]
    assert dc.stats(rows, "chill_portions") == {"typical": 2.0, "worst": -3.0, "mean": 0.0}
    assert "usually within 2.0" in dc.pitch_sentence(rows)
    assert "at most 3.0 off (3 winters, 2 stations)" in dc.pitch_sentence(rows)
