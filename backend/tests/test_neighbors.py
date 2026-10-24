"""Neighbor rules: one shared station pool, and only stations with data that season count."""
import os

os.environ["DATA_SOURCE"] = "synthetic"

import pandas as pd  # noqa: E402

from app import config, interp  # noqa: E402


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
    from app import data
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
    """A closed station counts as 'no data' unless it is already cached: no CIMIS request."""
    from app import data, main
    monkeypatch.setattr(data, "is_cached", lambda sid, year: False)

    def must_not_download(*args, **kwargs):
        raise AssertionError("tried to download a closed station")

    monkeypatch.setattr(data, "season_coverage", must_not_download)
    assert main.season_coverage_fn(2024)("12") == 0.0    # Durham (12) is closed
