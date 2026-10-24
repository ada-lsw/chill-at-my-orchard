"""The app must answer, not crash, when the forecast can't be fetched or a spot has no nearby station data."""
import os
from datetime import date

os.environ.setdefault("DATA_SOURCE", "synthetic")

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config, forecast, main  # noqa: E402

client = TestClient(main.app)


def test_estimate_for_today_works_when_the_forecast_is_unavailable(monkeypatch):
    """Offline, or with Open-Meteo down, 'today' falls back to past winters for the next 14 days."""
    monkeypatch.setattr(forecast.requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(config, "CACHE_DIR", config.CACHE_DIR)  # no saved forecast for this pin
    d = config.DEMO_ORCHARDS["durham"]
    r = client.get("/estimate", params={"lat": d["lat"] + 0.0123, "lon": d["lon"], "as_of": str(date.today()),
                                        "variety": d["variety"], "history_seasons": 3})
    assert r.status_code == 200, r.text
    assert r.json()["projection"].get("method") != "forecast"


def test_unavailable_forecast_has_a_time_index(monkeypatch):
    """An empty forecast still has a time index, so it can be compared with times."""
    monkeypatch.setattr(forecast.requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    s, source = forecast.hourly_forecast(1.2345, 2.3456)
    assert source == "unavailable" and s.empty
    assert isinstance(s.index, pd.DatetimeIndex)


def test_no_station_data_message_is_plain_and_points_to_the_demos():
    """Far from any station, the 404 explains in plain words what to do next."""
    r = client.get("/estimate", params={"lat": 41.9, "lon": -124.1, "as_of": "2026-02-01"})  # far from synthetic stations
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "demo" in detail.lower() and "km" in detail
