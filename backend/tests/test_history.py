"""The long view (/history): an honest trend sentence, and never a download.

Trend rule: say chill is falling or rising only when the 95% confidence range of the
straight-line slope stays on one side of zero; otherwise say there is no clear change.
"""
import inspect
import os
import time
from datetime import date, timedelta

os.environ["DATA_SOURCE"] = "synthetic"

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
import requests  # noqa: E402
from scipy import stats  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config, data, decision, interp, main  # noqa: E402

client = TestClient(main.app)


def rows_from(values, first_year=2010):
    """Season rows like /history's, one per value, starting with the winter of first_year."""
    return [{"season": f"{first_year + i}-{str(first_year + i + 1)[-2:]}", "chill_portions": float(v)}
            for i, v in enumerate(values)]


def test_flat_noisy_winters_give_no_clear_change():
    """Ups and downs around a flat level never read as falling or rising."""
    noise = np.random.default_rng(1).normal(0, 5, 15)
    trend = main.trend_fit(rows_from(60 + noise))
    assert trend["direction"] == "no clear change"


def test_a_real_but_noisy_slope_with_few_winters_is_no_clear_change():
    """A small decline buried in year-to-year swings, over 8 winters, is too uncertain to call."""
    trend = main.trend_fit(rows_from([66, 60, 67, 59, 65, 58, 66, 61]))
    assert trend["per_decade"] < 0                     # the fitted line does slope down...
    assert trend["direction"] == "no clear change"    # ...but not clearly enough to say so


def test_a_strong_decline_is_falling_and_the_sentence_gives_rate_and_share():
    """A clear decline is called falling, with the rate per decade and its share of a typical winter."""
    years = np.arange(12)
    noise = np.random.default_rng(3).normal(0, 0.5, 12)
    rows = rows_from(70 - 1.0 * years + noise)
    trend = main.trend_fit(rows)
    assert trend["direction"] == "falling"
    typical = float(np.median([r["chill_portions"] for r in rows]))
    sentence = decision.trend_sentence(trend["direction"], [r["season"] for r in rows],
                                       trend["per_decade"], typical)
    assert "fell" in sentence
    assert f"about {abs(trend['per_decade']):.1f} chill portions per decade" in sentence
    assert f"about {round(100 * abs(trend['per_decade']) / typical)}% of a typical winter here" in sentence
    assert "the last 12 winters" in sentence and "2010-11 to 2021-22" in sentence
    assert "Sep 1 to Mar 31" in sentence
    assert "Dynamic" not in sentence and "model" not in sentence.lower()


def test_the_95_percent_rule_decides_near_the_line():
    """Two 6-winter series either side of the 95% line (t distribution with 4 degrees of freedom).

    The first would read as falling with an 80% rule or a normal (z) value instead of t; the second
    would read as no clear change with a 99% rule. So these pin the rule Ada approved.
    """
    years = np.arange(2015, 2021)
    almost = [60, 58, 61, 55, 57, 54]                 # p = 0.079: not clear at 95%
    clear = [61, 60, 57, 59, 56, 56]                  # p = 0.022: clear at 95%
    assert 0.05 < stats.linregress(years, almost).pvalue < 0.10
    assert 0.01 < stats.linregress(years, clear).pvalue < 0.05
    assert main.trend_fit(rows_from(almost, 2015))["direction"] == "no clear change"
    assert main.trend_fit(rows_from(clear, 2015))["direction"] == "falling"


def test_direction_agrees_with_the_slope_test_on_random_winters():
    """Calling a trend clear is the same as the slope's two-sided test giving p < 0.05."""
    rng = np.random.default_rng(11)
    for _ in range(200):
        n = int(rng.integers(5, 25))
        values = 60 + rng.normal(0, 4, n) + rng.normal(0, 0.4) * np.arange(n)
        p = stats.linregress(np.arange(n), values).pvalue
        assert (main.trend_fit(rows_from(values))["direction"] != "no clear change") == (p < 0.05)


def test_a_strong_rise_is_rising_and_the_sentence_says_rose():
    years = np.arange(12)
    noise = np.random.default_rng(3).normal(0, 0.5, 12)
    rows = rows_from(58 + 1.0 * years + noise)
    trend = main.trend_fit(rows)
    assert trend["direction"] == "rising" and trend["per_decade"] > 0
    sentence = decision.trend_sentence(trend["direction"], [r["season"] for r in rows], trend["per_decade"], 64.0)
    assert "rose by about" in sentence and "fell" not in sentence


def test_winters_with_a_gap_are_not_called_the_last_n():
    """If a winter in the middle was skipped, the sentence names the span instead of 'the last N winters'."""
    sentence = decision.trend_sentence("no clear change", ["2015-16", "2016-17", "2018-19", "2019-20", "2020-21"],
                                       0.5, 60.0)
    assert "Over 5 winters here between 2015-16 and 2020-21" in sentence and "the last" not in sentence


def test_typical_winter_is_the_median(monkeypatch):
    """The rate's share is of the median winter here, so one extreme winter can't move it much."""
    rows = rows_from([50, 52, 54, 56, 100])
    seen = {}
    monkeypatch.setattr(main, "_season_total", lambda *a: (rows.pop(0) | {"hours_missing": 0}, None))
    monkeypatch.setattr(main, "pin_elevation", lambda lat, lon, exclude=(): (40.0, "test"))
    monkeypatch.setattr(decision, "trend_sentence",
                        lambda direction, labels, per_decade, typical, **k: seen.setdefault("typical", typical) and "")
    client.get("/history", params={"lat": 39.61, "lon": -121.82, "as_of": "2026-02-01", "max_seasons": 5})
    assert seen["typical"] == 54.0                     # the mean would be 62.4


def test_no_clear_change_sentence_never_says_too_few_with_enough_winters():
    """With at least MIN_TREND_SEASONS winters, "no clear change" is not "too few to tell" (43 winters isn't few)."""
    sentence = decision.trend_sentence("no clear change", ["2015-16", "2016-17", "2017-18", "2018-19",
                                                           "2019-20", "2020-21"], -1.2, 60.0)
    assert sentence == ("Over the last 6 winters here (2015-16 to 2020-21), chill shows no clear rise or fall. "
                        "Chill is counted from Sep 1 to Mar 31.")
    assert "too few" not in sentence and "fell" not in sentence and "rose" not in sentence


def test_only_the_too_few_path_says_too_few():
    """Fewer than MIN_TREND_SEASONS winters is the one place the sentence says "too few to tell"."""
    labels = [f"{2020 + i}-{21 + i}" for i in range(config.MIN_TREND_SEASONS - 1)]
    assert "too few to tell" in decision.trend_sentence("too few winters", labels, None, 60.0)
    for direction in ("no clear change", "falling", "rising"):
        many = [f"{1990 + i}-{str(1991 + i)[-2:]}" for i in range(43)]
        assert "too few" not in decision.trend_sentence(direction, many, -1.0, 60.0)


def test_trend_line_ends_and_rate_match_a_straight_line_fit():
    """trend_line's end points sit on the fitted line; trend_cp_per_decade keeps its old calculation."""
    values = [62, 58, 61, 55, 57, 54, 56, 51]
    rows = rows_from(values, first_year=2016)
    trend = main.trend_fit(rows)
    slope, intercept = np.polyfit(np.arange(2016, 2024), values, 1)
    line = trend["line"]
    assert line["start"]["season"] == "2016-17" and line["end"]["season"] == "2023-24"
    assert line["start"]["chill_portions"] == round(intercept + slope * 2016, 1)
    assert line["end"]["chill_portions"] == round(intercept + slope * 2023, 1)
    assert trend["per_decade"] == round(slope * 10, 1)


def test_fewer_than_the_minimum_winters_is_too_few():
    trend = main.trend_fit(rows_from([60, 55, 50]))
    assert trend == {"direction": "too few winters", "per_decade": None, "line": None}


@pytest.fixture
def saved_cimis_cache(tmp_path, monkeypatch):
    """Real-data mode against a scratch cache, with every download replaced by a recorder.

    Saves the given winters for the open stations near the Durham pin (SYN-A, B, C) and returns
    (save, asked): save(year) writes those files; asked lists every download attempt. Recorders,
    not errors: the app catches errors, so a raise would be swallowed and a test could never fail.
    """
    monkeypatch.setattr(config, "DATA_SOURCE", "cimis")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(data, "_COVERAGE", {})
    data._synthetic_stations().to_parquet(tmp_path / "stations.parquet")
    asked = []
    monkeypatch.setattr(data, "_cimis_hourly",
                        lambda sid, start, end: asked.append((sid, start)) or pd.DataFrame(columns=data.CONTRACT))
    monkeypatch.setattr(requests, "get", lambda *a, **k: asked.append(a) or None)
    monkeypatch.setattr(main, "pin_elevation", lambda lat, lon, exclude=(): (40.0, "test"))

    def save(year: int) -> list:
        """Save one winter for SYN-A, B and C (2022-23 with a 10-hour gap at all three); returns the file paths."""
        paths = []
        for sid in ("SYN-A", "SYN-B", "SYN-C"):
            end = min(date(year + 1, 8, 31), date.today() - timedelta(days=1))
            path = tmp_path / f"hourly_cimis_{sid}_{year}.parquet"
            hourly = data.fill_gaps(data._synthetic_hourly(sid, date(year, 9, 1), end))
            if year == 2022:                  # every station lost the same 10 hours on Dec 10, 2022
                gap = (hourly["datetime"] >= "2022-12-10 06:00") & (hourly["datetime"] < "2022-12-10 16:00")
                hourly.loc[gap, "temp_F"] = float("nan")
            hourly.to_parquet(path)
            paths.append(path)
        return paths
    return save, asked


def test_history_never_downloads_and_lists_the_winters_it_skipped(saved_cimis_cache):
    """/history reads only saved station data: winters with nothing saved are skipped and listed."""
    save, asked = saved_cimis_cache
    for y in range(2020, 2025):
        save(y)
    r = client.get("/history", params={"lat": 39.61, "lon": -121.82, "as_of": "2026-02-01", "max_seasons": 15,
                                         "source": "stations"})
    assert r.status_code == 200, r.text
    h = r.json()
    assert asked == []                                                 # nothing was downloaded
    assert [s["season"] for s in h["seasons"]] == ["2020-21", "2021-22", "2022-23", "2023-24", "2024-25"]
    assert h["seasons_used"] == 5
    assert [s["season"] for s in h["seasons_skipped"]] == [f"{y}-{str(y + 1)[-2:]}" for y in range(2010, 2020)]
    assert all(s["reason"] for s in h["seasons_skipped"])
    assert {s["season"]: s["hours_missing"] for s in h["seasons"]} == {
        "2020-21": 0, "2021-22": 0, "2022-23": 10, "2023-24": 0, "2024-25": 0}   # the gap no neighbor covers
    assert h["trend_direction"] in ("falling", "rising", "no clear change")
    assert h["trend_sentence"].startswith("Over the last 5 winters here (2020-21 to 2024-25)")


def test_history_never_refreshes_a_saved_season_still_in_progress(saved_cimis_cache):
    """A saved file for today's season is refreshed once a day by data.season_hourly, which downloads.

    /history must skip that season instead, even when its file is a day old.
    """
    save, asked = saved_cimis_cache
    this_season = data.season_year(date.today())
    old = time.time() - 3 * 86400
    for path in save(this_season):
        os.utime(path, (old, old))                                    # three days old: stale
    as_of = date(this_season + 1, 10, 1)                               # in the next season
    r = client.get("/history", params={"lat": 39.61, "lon": -121.82, "as_of": str(as_of), "max_seasons": 1,
                                         "source": "stations"})
    assert r.status_code == 200, r.text
    assert asked == []
    assert r.json()["seasons_skipped"] == [{"season": f"{this_season}-{str(this_season + 1)[-2:]}",
                                            "reason": "this winter is not finished yet"}]


def test_history_skips_a_season_that_is_not_finished():
    """A season still in progress is skipped (its saved file may be refreshed, which downloads)."""
    future = date(date.today().year + 2, 2, 1)
    r = client.get("/history", params={"lat": 39.61, "lon": -121.82, "as_of": str(future), "max_seasons": 1})
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["seasons"] == [] and h["seasons_used"] == 0
    assert len(h["seasons_skipped"]) == 1 and "not finished" in h["seasons_skipped"][0]["reason"]
    assert h["trend_direction"] == "too few winters" and h["trend_line"] is None


def test_history_on_synthetic_data_has_every_new_field():
    """Synthetic data is made on this machine (no download), so every winter counts."""
    r = client.get("/history", params={"lat": 39.61, "lon": -121.82, "as_of": "2026-02-01", "max_seasons": 6})
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["seasons_used"] == 6 and h["seasons_skipped"] == []
    assert h["trend_cp_per_decade"] is not None and h["trend_line"] is not None
    assert h["trend_sentence"] and h["trend_direction"]
    assert all(s["hours_missing"] >= 0 for s in h["seasons"])


# ---------------------------------------------------------------- long view from FNRIC daily chill (B3)

FNRIC_COLUMNS = ["Date", "hours_lt_45", "hours_32_45", "units_utah", "portions_dynamic"]
HISTORY_FIELDS = {"location", "season_end", "seasons", "trend_cp_per_decade", "source", "trend_sentence",
                  "trend_direction", "trend_line", "seasons_used", "seasons_skipped"}


def write_fnric(folder, station_id: str, years, portions_per_day, drop_days=(), zero_days=()):
    """Save a tiny FNRIC CSV: every day from Sept 1 to Mar 31 of each winter, the same daily portions.

    portions_per_day: one number for every winter, or a dict {winter start year: number}.
    drop_days: dates written as a row of empty values (how FNRIC marks a day with no data).
    zero_days: dates written as 0 in all four columns (how some FNRIC gaps look; they count as missing).
    """
    lines = [",".join(f'"{c}"' for c in FNRIC_COLUMNS)]
    for y in years:
        cp = portions_per_day[y] if isinstance(portions_per_day, dict) else portions_per_day
        for d in pd.date_range(date(y, 9, 1), date(y + 1, 3, 31), freq="D"):
            if d.date() in drop_days:
                lines.append(f'"{d.date()}",,,,')
            elif d.date() in zero_days:
                lines.append(f'"{d.date()}",0,0,0,0')
            else:
                lines.append(f'"{d.date()}",1.0,1.0,1.0,{cp}')
    (folder / f"fnric_CIMIS-{station_id}.csv").write_text("\n".join(lines) + "\n")


def _no_web(asked):
    """A stand-in for requests.get that records the call and fails it (nothing may be downloaded)."""
    def get(*a, **k):
        asked.append(a)
        raise AssertionError("the long view must never download")
    return get


@pytest.fixture
def fnric_cache(tmp_path, monkeypatch):
    """Real-data mode on a scratch cache with three stations near a pin, and every download recorded.

    Station 1 sits 0.2 km from the pin (closer than interp's 0.5 km floor), 2 about 10 km, 3 about 20 km.
    Returns (folder, stations, asked): asked lists every web request (there must be none).
    """
    monkeypatch.setattr(config, "DATA_SOURCE", "cimis")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    stations = pd.DataFrame({
        "station_id": ["1", "2", "3"], "name": ["One", "Two", "Three"], "county": ["X"] * 3,
        "lat": [39.6118, 39.70, 39.79], "lon": [-121.82] * 3, "elev_m": [40.0] * 3, "active": [True] * 3})
    monkeypatch.setattr(data, "get_stations", lambda: stations.copy())
    monkeypatch.setattr(main, "pin_elevation", lambda lat, lon, exclude=(): (40.0, "test"))
    asked = []
    monkeypatch.setattr(requests, "get", _no_web(asked))
    monkeypatch.setattr(data, "_cimis_hourly", lambda *a, **k: asked.append(a) or pd.DataFrame(columns=data.CONTRACT))
    return tmp_path, stations, asked


def fnric_history(**params):
    """GET /history at the fixture pin from FNRIC history; returns the JSON."""
    r = client.get("/history", params={"lat": 39.61, "lon": -121.82, "as_of": "2023-02-01", "source": "fnric",
                                       **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_fnric_blend_uses_interp_idw_weights(fnric_cache):
    """Each day is the inverse-distance blend interp.py uses (1 / max(km, 0.5) ** IDW_POWER, NEIGHBORS stations).

    Station 2 has no data on Dec 1, 2020, so that day blends stations 1 and 3 only.
    """
    folder, stations, _ = fnric_cache
    values = {"1": 0.5, "2": 0.3, "3": 0.1}
    gap = date(2020, 12, 1)
    for sid, v in values.items():
        write_fnric(folder, sid, [2020, 2021], v, drop_days=(gap,) if sid == "2" else ())
    km = {r.station_id: float(interp.haversine_km(39.61, -121.82, r.lat, r.lon)) for r in stations.itertuples()}
    assert km["1"] < 0.5                                           # the 0.5 km floor matters here
    w = {sid: 1.0 / max(d, 0.5) ** config.IDW_POWER for sid, d in km.items()}

    def blend(sids):
        return sum(w[s] * values[s] for s in sids) / sum(w[s] for s in sids)
    days = (date(2021, 3, 31) - date(2020, 9, 1)).days + 1
    expected = (days - 1) * blend(["1", "2", "3"]) + blend(["1", "3"])
    h = fnric_history()
    by_season = {s["season"]: s for s in h["seasons"]}
    assert by_season["2020-21"]["chill_portions"] == round(expected, 1)
    assert by_season["2020-21"]["days_missing"] == 0              # another station covered the gap
    assert by_season["2021-22"]["chill_portions"] == round(((date(2022, 3, 31) - date(2021, 9, 1)).days + 1)
                                                           * blend(["1", "2", "3"]), 1)


def test_fnric_history_keeps_every_trend_field_and_lists_skipped_winters(fnric_cache):
    """Winters with no FNRIC data near the pin are skipped and listed; every history-trend field is there."""
    folder, _, _ = fnric_cache
    for sid in ("1", "2"):
        write_fnric(folder, sid, range(2012, 2022), 0.3 + 0.01 * int(sid))
    h = fnric_history()
    assert HISTORY_FIELDS <= set(h)
    assert h["seasons_used"] == 10
    assert h["seasons"][0]["season"] == "2012-13" and h["seasons"][-1]["season"] == "2021-22"
    skipped = [s["season"] for s in h["seasons_skipped"]]
    assert "2011-12" in skipped and len(skipped) == config.LONG_VIEW_MAX_SEASONS - 10
    assert all(s["reason"] for s in h["seasons_skipped"])
    assert h["trend_direction"] in ("falling", "rising", "no clear change")
    assert h["trend_sentence"].startswith("Over the last 10 winters here (2012-13 to 2021-22)")


def test_fnric_missing_days_are_reported_never_filled(fnric_cache):
    """A day no neighbor has stays out of the total and is counted in days_missing (and hours_missing)."""
    folder, _, _ = fnric_cache
    gap = date(2022, 1, 15)
    for sid in ("1", "2", "3"):
        write_fnric(folder, sid, [2021], 1.0, drop_days=(gap,))
    s = fnric_history()["seasons"][0]
    days = (date(2022, 3, 31) - date(2021, 9, 1)).days + 1
    assert s["season"] == "2021-22" and s["days_missing"] == 1 and s["hours_missing"] == 24
    assert s["chill_portions"] == days - 1


def test_fnric_history_never_calls_the_downloader(fnric_cache, monkeypatch):
    """/history reads FNRIC files only with download=False, and never makes a web request."""
    folder, _, asked = fnric_cache
    write_fnric(folder, "1", [2021], 0.4)
    from app import fnric
    real = fnric.daily_chill
    calls = []

    def no_download(station_id, download=False):
        calls.append(download)
        if download:
            raise AssertionError("the long view must never download from FNRIC")
        return real(station_id, download=False)
    monkeypatch.setattr(fnric, "daily_chill", no_download)
    h = fnric_history()
    assert h["seasons_used"] == 1
    assert calls and not any(calls) and asked == []


def test_real_data_mode_defaults_to_fnric_and_reaches_back(fnric_cache):
    """Without a source or max_seasons, real-data mode uses FNRIC and looks back LONG_VIEW_MAX_SEASONS winters."""
    folder, _, _ = fnric_cache
    write_fnric(folder, "1", range(1985, 2022), 0.4)
    r = client.get("/history", params={"lat": 39.61, "lon": -121.82, "as_of": "2023-02-01"})
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["source"] == "fnric" and h["seasons_used"] == 37
    assert h["seasons"][0]["season"] == "1985-86"
    assert h["seasons_used"] + len(h["seasons_skipped"]) == config.LONG_VIEW_MAX_SEASONS


def test_max_seasons_defaults_to_the_config_cap():
    """max_seasons is optional; its default is config.LONG_VIEW_MAX_SEASONS on every path."""
    assert inspect.signature(main.history_endpoint).parameters["max_seasons"].default.default \
        == config.LONG_VIEW_MAX_SEASONS


def test_fnric_path_honors_max_seasons(fnric_cache):
    """A caller asking for 15 winters gets at most 15 (counted and skipped together), never 43."""
    folder, _, _ = fnric_cache
    write_fnric(folder, "1", range(1985, 2022), 0.4)
    h = fnric_history(max_seasons=15)
    assert h["source"] == "fnric"
    assert h["seasons_used"] + len(h["seasons_skipped"]) == 15
    assert h["seasons"][0]["season"] == "2007-08" and h["seasons"][-1]["season"] == "2021-22"


def test_stations_path_honors_max_seasons_and_says_its_source():
    """source=stations rebuilds winters from saved hourly data, max_seasons of them; source names the data used."""
    r = client.get("/history", params={"lat": 39.61, "lon": -121.82, "as_of": "2026-02-01", "max_seasons": 3,
                                       "source": "stations"})
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["source"] == config.DATA_SOURCE == "synthetic" and h["seasons_used"] == 3


def test_all_zero_fnric_days_are_missing_and_neighbors_carry_them(fnric_cache):
    """A day written as 0 in all four columns is a gap: that station drops out of the day's blend.

    Station 2 has a zero row on Dec 1, 2020; stations 1 and 3 carry the day, so nothing is missing and the
    total is the blend of 1 and 3 on that day (not a blend pulled down by station 2's fake 0).
    """
    folder, stations, _ = fnric_cache
    values = {"1": 0.5, "2": 0.3, "3": 0.1}
    gap = date(2020, 12, 1)
    for sid, v in values.items():
        write_fnric(folder, sid, [2020], v, zero_days=(gap,) if sid == "2" else ())
    km = {r.station_id: float(interp.haversine_km(39.61, -121.82, r.lat, r.lon)) for r in stations.itertuples()}
    w = {sid: 1.0 / max(d, 0.5) ** config.IDW_POWER for sid, d in km.items()}

    def blend(sids):
        return sum(w[s] * values[s] for s in sids) / sum(w[s] for s in sids)
    days = (date(2021, 3, 31) - date(2020, 9, 1)).days + 1
    s = fnric_history()["seasons"][0]
    assert s["days_missing"] == 0 and s["complete"] is True
    assert s["chill_portions"] == round((days - 1) * blend(["1", "2", "3"]) + blend(["1", "3"]), 1)


def test_a_day_all_stations_write_as_zero_is_missing(fnric_cache):
    """If every neighbor has a zero row on a day, the day is missing (days_missing), never 0 chill."""
    folder, _, _ = fnric_cache
    gaps = (date(2022, 1, 15), date(2022, 1, 16))
    for sid in ("1", "2", "3"):
        write_fnric(folder, sid, [2021], 1.0, zero_days=gaps)
    s = fnric_history()["seasons"][0]
    days = (date(2022, 3, 31) - date(2021, 9, 1)).days + 1
    assert s["days_missing"] == 2 and s["hours_missing"] == 48 and s["complete"] is False
    assert s["chill_portions"] == days - 2


def test_incomplete_winters_are_shown_flagged_but_left_out_of_the_trend(fnric_cache):
    """A winter with any missing day stays in seasons (complete: false) but never enters the trend fit.

    Ten flat complete winters, then three recent winters with a 60-day gap written as zeros. Counted as
    zero chill, those gaps would make the trend "falling"; left out, the trend is flat.
    """
    folder, _, _ = fnric_cache
    years = range(2009, 2022)
    gap = {d.date() for y in (2019, 2020, 2021) for d in pd.date_range(date(y, 11, 15), periods=60, freq="D")}
    noise = {y: 0.30 + 0.01 * ((y * 7) % 5) for y in years}
    for sid in ("1", "2", "3"):
        write_fnric(folder, sid, years, noise, zero_days=gap)
    h = fnric_history()
    flags = {s["season"]: s["complete"] for s in h["seasons"]}
    assert len(flags) == 13 and h["seasons_used"] == 13
    assert [k for k, ok in flags.items() if not ok] == ["2019-20", "2020-21", "2021-22"]
    assert h["seasons_in_trend"] == 10
    expected = main.trend_fit([s for s in h["seasons"] if s["complete"]])
    assert h["trend_direction"] == expected["direction"] != "falling"
    assert h["trend_cp_per_decade"] == expected["per_decade"]
    assert h["trend_line"]["end"]["season"] == "2018-19"          # the line ends at the last winter in the fit
    # Later winters are shown but left out, so these 10 are not "the last 10 winters"
    assert h["trend_sentence"].startswith("Over 10 winters here between 2009-10 and 2018-19")
