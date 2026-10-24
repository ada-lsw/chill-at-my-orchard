"""Neighbor rules: one shared station pool, and only stations with data that season count."""
import logging
import os
from datetime import date

os.environ["DATA_SOURCE"] = "synthetic"

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from app import config, data, interp, main  # noqa: E402

FAKE_KEY = "FAKE-KEY-0123456789abcdef0123456"


def stations():
    """Four made-up stations east of a pin at (38.0, -121.0, 50 m), closest first."""
    return pd.DataFrame({
        "station_id": ["A", "B", "C", "D"],
        "name": ["Near", "Closed", "Next", "Hilltop"],
        "lat": [38.0, 38.0, 38.0, 38.0],
        "lon": [-120.9, -120.8, -120.7, -120.6],     # about 9, 18, 26, 35 km away
        "elev_m": [40.0, 60.0, 80.0, 50.0 + config.MAX_ELEV_DIFF_M + 100],
        "active": [True, False, True, True],
    })


def test_candidates_closest_first_and_drops_station_too_high():
    c = interp.candidates(stations(), 38.0, -121.0, 50.0)
    assert list(c["station_id"]) == ["A", "B", "C"]   # D is too far above the pin


def test_candidates_drops_station_too_far(monkeypatch):
    monkeypatch.setattr(config, "MAX_NEIGHBOR_KM", 20)
    c = interp.candidates(stations(), 38.0, -121.0, 50.0)
    assert list(c["station_id"]) == ["A", "B"]


def test_candidates_keeps_closed_stations_and_respects_exclude():
    c = interp.candidates(stations(), 38.0, -121.0, 50.0, exclude=["A"])
    assert "B" in set(c["station_id"])                 # closed, but its old data may help
    assert "A" not in set(c["station_id"])


def test_station_without_data_is_replaced_by_next_closest():
    """B was closed this winter: the estimate uses A and C, not just A."""
    cands = interp.candidates(stations(), 38.0, -121.0, 50.0)
    share = {"A": 1.0, "B": 0.0, "C": 0.99}
    picked = interp.pick_neighbors(cands, share.get, k=2)
    assert list(picked["station_id"]) == ["A", "C"]


def test_station_with_too_little_data_is_skipped(monkeypatch):
    """A station with data for under MIN_NEIGHBOR_COVERAGE of the season doesn't count."""
    monkeypatch.setattr(config, "MIN_NEIGHBOR_COVERAGE", 0.5)
    cands = interp.candidates(stations(), 38.0, -121.0, 50.0)
    share = {"A": 0.2, "B": 1.0, "C": 1.0}
    picked = interp.pick_neighbors(cands, share.get, k=2)
    assert list(picked["station_id"]) == ["B", "C"]


def test_walk_stops_once_enough_stations_are_found():
    """Farther stations are never looked at (or downloaded) when closer ones have data."""
    cands = interp.candidates(stations(), 38.0, -121.0, 50.0)
    asked = []

    def share(sid):
        asked.append(sid)
        return 1.0

    picked = interp.pick_neighbors(cands, share, k=2)
    assert list(picked["station_id"]) == ["A", "B"]
    assert asked == ["A", "B"]


def test_season_coverage_on_synthetic_data():
    """Synthetic seasons are almost full; a season that hasn't started has no data."""
    assert data.season_coverage("SYN-A", 2024) > 0.9      # ~1% of synthetic hours are missing
    assert data.season_coverage("SYN-A", 2099) == 0.0     # a season that hasn't started


def test_pin_elevation_is_saved_for_offline_use(tmp_path, monkeypatch):
    """Looked up once online, the same elevation comes back with no internet."""
    monkeypatch.setattr(interp, "ELEVATION_CACHE", tmp_path / "elevations.json")
    calls = []

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"elevation": [123.0]}

    def fake_get(*args, **kwargs):
        calls.append(1)
        return Reply()

    monkeypatch.setattr(interp.requests, "get", fake_get)
    assert interp.elevation_m(39.61, -121.82) == 123.0

    def offline(*args, **kwargs):
        raise ConnectionError("no Wi-Fi")

    monkeypatch.setattr(interp.requests, "get", offline)
    assert interp.elevation_m(39.61, -121.82) == 123.0
    assert len(calls) == 1


def test_app_never_downloads_an_uncached_closed_station(monkeypatch):
    """A closed station counts as 'no data' unless it is already cached: no CIMIS request.

    Records calls instead of raising: season_coverage_fn catches errors, so a raise here would
    be swallowed and the test could never fail.
    """
    monkeypatch.setattr(data, "is_cached", lambda sid, year: False)
    asked = []
    monkeypatch.setattr(data, "season_coverage", lambda sid, year: asked.append(sid) or 1.0)
    assert main.season_coverage_fn(2024)("12") == 0.0    # Durham (12) is closed
    assert asked == []                                   # no download was attempted


@pytest.fixture
def fake_key(monkeypatch, caplog):
    """Pretend a CIMIS key is set and capture app.main's warnings, so a test can check the key isn't logged."""
    monkeypatch.setattr(config, "CIMIS_APP_KEY", FAKE_KEY)
    caplog.set_level(logging.WARNING, logger="app.main")
    return FAKE_KEY


def test_station_that_cannot_load_is_logged_without_the_key(fake_key, monkeypatch, caplog):
    """A station whose season can't load still counts as 'no data', but leaves a warning, never the key."""
    def refused(station_id, year):
        raise RuntimeError(f"CIMIS refused key {fake_key}")

    monkeypatch.setattr(data, "season_coverage", refused)
    assert main.season_coverage_fn(2024)("SYN-A") == 0.0   # SYN-A is active, so it reaches the download
    assert "SYN-A" in caplog.text and "2024-25" in caplog.text and "RuntimeError" in caplog.text
    assert fake_key not in caplog.text


def test_load_hourly_warns_about_a_failed_station_and_keeps_the_rest(fake_key, monkeypatch, caplog):
    """One station failing to load is logged (without the key); the other stations are still returned."""
    hours = pd.date_range("2024-11-01", periods=3, freq="h")

    def get_hourly(station_id, start, end):
        if station_id == "SYN-B":
            raise RuntimeError(f"CIMIS refused key {fake_key}")
        return pd.DataFrame({"datetime": hours, "temp_F": [40.0, 41.0, 42.0]})

    monkeypatch.setattr(data, "get_hourly", get_hourly)
    loaded = main.load_hourly(["SYN-A", "SYN-B", "SYN-C"], date(2024, 11, 1), date(2024, 11, 30))
    assert sorted(loaded) == ["SYN-A", "SYN-C"]
    assert "SYN-B" in caplog.text and "2024-25" in caplog.text and "RuntimeError" in caplog.text
    assert fake_key not in caplog.text


def test_history_skips_a_winter_with_no_station_data(monkeypatch):
    """A winter where no neighbor has data (offline and not cached) is left out of /history, not a crash.

    The long view asks for 15 winters; offline, the oldest ones have no cached station, so the
    estimate for them is empty. Before the fix that empty estimate crashed main.clip (500).
    """
    from fastapi.testclient import TestClient

    real_coverage_fn = main.season_coverage_fn
    monkeypatch.setattr(main, "season_coverage_fn",
                        lambda year: (lambda sid: 0.0) if year < 2022 else real_coverage_fn(year))
    r = TestClient(main.app).get("/history", params={"lat": 39.61, "lon": -121.82,
                                                     "as_of": "2026-02-01", "max_seasons": 5})
    assert r.status_code == 200, r.text
    assert [s["season"] for s in r.json()["seasons"]] == ["2022-23", "2023-24", "2024-25"]
