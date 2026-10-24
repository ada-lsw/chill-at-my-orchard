"""Neighbor rules: one shared station pool, and only stations with data in the window count."""
import os

os.environ["DATA_SOURCE"] = "synthetic"

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app import config, interp  # noqa: E402

START, END = pd.Timestamp("2024-11-01"), pd.Timestamp("2024-11-30")
HOURS = pd.date_range(START, END + pd.Timedelta(hours=23), freq="h")


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


def full(value=40.0):
    return pd.Series(value, index=HOURS)


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


def test_coverage_counts_share_of_hours():
    s = full()
    assert interp.coverage(s, START, END) == 1.0
    half = s.copy()
    half.iloc[: len(half) // 2] = np.nan
    assert abs(interp.coverage(half, START, END) - 0.5) < 0.01
    assert interp.coverage(None, START, END) == 0.0


def test_station_without_data_is_replaced_by_next_closest():
    """B closed before this winter: the estimate uses A and C, not just A."""
    cands = interp.candidates(stations(), 38.0, -121.0, 50.0)
    hourly = {"A": full(), "C": full()}               # B has no data in this window
    picked = interp.pick_neighbors(hourly, cands, START, END, k=2)
    assert list(picked["station_id"]) == ["A", "C"]


def test_station_with_too_little_data_is_skipped(monkeypatch):
    monkeypatch.setattr(config, "MIN_NEIGHBOR_COVERAGE", 0.5)
    cands = interp.candidates(stations(), 38.0, -121.0, 50.0)
    sparse = full()
    sparse.iloc[: int(len(sparse) * 0.8)] = np.nan       # only 20% of hours
    picked = interp.pick_neighbors({"A": sparse, "B": full(), "C": full()}, cands, START, END, k=2)
    assert list(picked["station_id"]) == ["B", "C"]


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
