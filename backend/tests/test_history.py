"""The long view (/history): an honest trend sentence, and never a download.

Trend rule: say chill is falling or rising only when the 95% confidence range of the
straight-line slope stays on one side of zero; otherwise say there is no clear change.
"""
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

from app import config, data, decision, main  # noqa: E402

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


def test_no_clear_change_sentence_says_too_few_winters_to_tell():
    sentence = decision.trend_sentence("no clear change", ["2015-16", "2016-17", "2017-18", "2018-19",
                                                           "2019-20", "2020-21"], -1.2, 60.0)
    assert "no clear" in sentence and "6 winters is too few to tell" in sentence
    assert "fell" not in sentence and "rose" not in sentence


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
    monkeypatch.setattr(main, "pin_elevation", lambda lat, lon: (40.0, "test"))

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
    r = client.get("/history", params={"lat": 39.61, "lon": -121.82, "as_of": "2026-02-01", "max_seasons": 15})
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
    r = client.get("/history", params={"lat": 39.61, "lon": -121.82, "as_of": str(as_of), "max_seasons": 1})
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
