"""FNRIC client: daily chill per station, downloaded once and cached, never by accident.

Every test points the cache at a scratch folder and replaces requests.get, so CI never calls FNRIC.
"""
import json
import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import requests

from app import config, fnric

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeResponse:
    """Just enough of requests.Response for fnric: text, status and raise_for_status()."""

    def __init__(self, text: str, status: int = 200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return json.loads(self.text)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """A scratch cache folder, and a list of every web request made (none should be, unless a test allows it)."""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    asked = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: asked.append((a, k)) or FakeResponse("", 500))
    return tmp_path, asked


def test_station_ids_are_fnric_form():
    assert fnric.fnric_id("6") == "CIMIS-6"
    assert fnric.fnric_id("CIMIS-6") == "CIMIS-6"
    assert fnric.fnric_id("Wildeye-111090") == "Wildeye-111090"


def test_cached_csv_loads_sorted_by_date_without_a_request(cache):
    folder, asked = cache
    shutil.copy(FIXTURES / "fnric_CIMIS-6.csv", folder / "fnric_CIMIS-6.csv")
    daily = fnric.daily_chill("6")
    assert asked == []
    assert list(daily["Date"]) == sorted(daily["Date"])
    assert daily["Date"].iloc[0] == pd.Timestamp("2024-08-31")
    assert list(daily.columns) == ["Date", *fnric.COLUMNS]


def test_season_totals_sum_daily_amounts_inside_the_window_only(cache):
    """Sept 1, 2024 to Feb 28, 2025, both ends included; Aug 31, Mar 1 and Sept 2025 are outside.

    FNRIC writes a day with no data as a row of empty values (Oct 1 in the fixture): it is a missing
    day, never a day with 0 chill.
    """
    folder, _ = cache
    shutil.copy(FIXTURES / "fnric_CIMIS-6.csv", folder / "fnric_CIMIS-6.csv")
    totals = fnric.season_totals(fnric.daily_chill("6"), date(2024, 9, 1), date(2025, 2, 28))
    assert totals["days"] == 5                                # Sept 1, Nov 1, Dec 15, Jan 10, Feb 28
    assert totals["days_missing"] == 181 - 5                  # every other day of the window, Oct 1 included
    assert totals["hours_lt_45"] == 0 + 3 + 14 + 18 + 5
    assert totals["hours_32_45"] == 0 + 3 + 12 + 15 + 4
    assert totals["units_utah"] == pytest.approx(-8.0 + 2.0 + 6.5 + 8.0 + 3.5)
    assert totals["portions_dynamic"] == pytest.approx(0.0 + 0.4 + 1.1 + 1.4 + 0.6)


def test_uncached_station_by_default_is_empty_and_asks_nothing(cache):
    """The default never downloads, so a loop over stations (the long view) can't spend FNRIC's budget."""
    _, asked = cache
    daily = fnric.daily_chill("6")
    assert asked == []
    assert daily.empty and list(daily.columns) == ["Date", *fnric.COLUMNS]


def test_download_asks_once_then_reads_the_saved_file(cache, monkeypatch):
    folder, asked = cache
    csv_text = (FIXTURES / "fnric_CIMIS-6.csv").read_text()
    monkeypatch.setattr(requests, "get", lambda url, **k: asked.append((url, k)) or FakeResponse(csv_text))
    first = fnric.daily_chill("6", download=True)
    second = fnric.daily_chill("6", download=True)
    assert len(asked) == 1
    url, kwargs = asked[0]
    assert url.endswith("/chill-models-download") and kwargs["params"] == {"station-id": "CIMIS-6"}
    assert (folder / "fnric_CIMIS-6.csv").exists()
    pd.testing.assert_frame_equal(first, second)


GOOD_CSV = "Date,hours_lt_45,hours_32_45,units_utah,portions_dynamic\n2024-12-01,10,9,5.0,0.8\n"


@pytest.mark.parametrize("response", [FakeResponse("Date,hours_lt_45,hours_32_45,units_utah,portions_dynamic\n"),
                                      FakeResponse("Date,hours_lt_45,hours_32_45,units_utah,portions_dynamic\n2024-12-01,,,,\n"),
                                      FakeResponse('{"message": "Internal server error"}'),
                                      FakeResponse(GOOD_CSV, 502)])
def test_a_bad_answer_raises_and_saves_nothing(cache, monkeypatch, response):
    """Each station is downloaded once ever, so a bad answer must never be saved as if it were the data."""
    folder, _ = cache
    monkeypatch.setattr(requests, "get", lambda *a, **k: response)
    with pytest.raises((requests.HTTPError, ValueError)):
        fnric.daily_chill("6", download=True)
    assert list(folder.iterdir()) == []


def test_stations_parses_coordinates_and_reads_the_cache(cache):
    folder, asked = cache
    shutil.copy(FIXTURES / "fnric_stations.json", folder / "fnric_stations.json")
    st = fnric.stations().set_index("station_id")
    assert asked == []
    assert st.loc["CIMIS-6", "lat"] == pytest.approx(38.535694)
    assert st.loc["CIMIS-6", "lon"] == pytest.approx(-121.776360)
    assert bool(st.loc["CIMIS-12", "active"]) is False


def test_stations_by_default_asks_nothing_when_not_cached(cache):
    _, asked = cache
    assert fnric.stations().empty and asked == []


def test_stations_download_saves_the_list_once(cache, monkeypatch):
    folder, asked = cache
    text = (FIXTURES / "fnric_stations.json").read_text()
    monkeypatch.setattr(requests, "get", lambda url, **k: asked.append(url) or FakeResponse(text))
    first = fnric.stations(download=True)
    second = fnric.stations(download=True)
    assert len(asked) == 1 and asked[0].endswith("/stations")
    assert (folder / "fnric_stations.json").exists()
    pd.testing.assert_frame_equal(first, second)
