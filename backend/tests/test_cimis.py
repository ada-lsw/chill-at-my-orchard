"""New CIMIS request format, checked without a network or a real key."""
from datetime import date

import pandas as pd
import pytest

from app import config, data


class FakeResponse:
    def __init__(self, text, status=200, ctype="application/json; charset=utf-8", payload=None):
        self.text, self.status_code, self.headers, self._payload = text, status, {"Content-Type": ctype}, payload

    def json(self):
        return self._payload


def records(day, n=3):
    return [{"Date": day, "Hour": f"{h:02d}00", "Station": "6", "HlyAirTmp": {"Value": f"{40 + h}", "Qc": " "}}
            for h in range(1, n + 1)]


@pytest.fixture
def stations(monkeypatch):
    st = pd.DataFrame([{"station_id": "6", "name": "Davis", "county": "Yolo", "lat": 38.5, "lon": -121.8,
                        "elev_m": 18.0, "active": True}])
    monkeypatch.setattr(data, "get_stations", lambda: st)
    monkeypatch.setattr(config, "CIMIS_APP_KEY", "a" * 32)


def test_key_goes_in_header_not_url(monkeypatch, stations):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers)
        return FakeResponse("{}", payload={"Data": {"Providers": [{"Records": records("2026-01-05")}]}})

    monkeypatch.setattr(data.requests, "get", fake_get)
    df = data._cimis_hourly("6", date(2026, 1, 5), date(2026, 1, 5))
    assert seen["url"].endswith("/StationWeb/GetDataByStationNumber")
    assert seen["headers"]["Ocp-Apim-Subscription-Key"] == "a" * 32
    assert "appKey" not in seen["params"] and seen["params"]["isHourly"] == "true"
    assert seen["params"]["stationNbrs"] == "6"
    assert list(df["temp_F"]) == [41.0, 42.0, 43.0]
    assert df["datetime"].iloc[0] == pd.Timestamp("2026-01-05 01:00")


def test_too_large_request_is_split(monkeypatch, stations):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((params["startDate"], params["endDate"]))
        if params["startDate"] != params["endDate"]:
            return FakeResponse("[ERR2112-DATA VOLUME VIOLATION] too many records", status=400)
        return FakeResponse("{}", payload={"Data": {"Providers": [{"Records": records(params["startDate"], 1)}]}})

    monkeypatch.setattr(data.requests, "get", fake_get)
    df = data._cimis_hourly("6", date(2026, 1, 1), date(2026, 1, 4))
    assert len(df) == 4  # one record per day, all four days recovered after splitting


def test_firewall_page_gives_a_clear_error(monkeypatch, stations):
    monkeypatch.setattr(data.requests, "get",
                        lambda *a, **k: FakeResponse("<html>Request Rejected</html>", ctype="text/html"))
    with pytest.raises(RuntimeError, match="instead of data"):
        data._cimis_hourly("6", date(2026, 1, 5), date(2026, 1, 5))
