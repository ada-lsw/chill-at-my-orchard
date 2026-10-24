"""GET /daily.csv: the season's daily chill as a spreadsheet file (work package G4).

Checked on synthetic data (no CIMIS key or internet needed). The file must open in Excel, so it is
plain CSV: one header row, no comment lines, dates as YYYY-MM-DD.
"""
import csv
import io
import os
from datetime import date, timedelta

os.environ["DATA_SOURCE"] = "synthetic"

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import app, daily_chill_table  # noqa: E402

client = TestClient(app)

DURHAM = {"lat": 39.61, "lon": -121.82, "as_of": "2026-02-01", "variety": "Chandler walnut", "exclude": ["12"]}
START = date(2025, *config.CHILL_START)
SINCE = f"since_{START:%b}_{START.day}".lower()      # "since_sep_1" with the default start
MEASURES = ("chill_portions", "chill_hours_32_45", "hours_at_or_below_45", "utah_units")
HEADER = ["date"] + [f"{m}_{part}" for m in MEASURES for part in ("day", SINCE)] + ["hours_missing"]


def _rows(params: dict) -> tuple[list[str], list[dict]]:
    """Fetch /daily.csv and parse it with Python's csv module: (header, rows as dicts)."""
    r = client.get("/daily.csv", params=params)
    assert r.status_code == 200, r.text
    reader = csv.DictReader(io.StringIO(r.text))
    return reader.fieldnames, list(reader)


def test_csv_is_a_named_attachment():
    r = client.get("/daily.csv", params=DURHAM)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="chill_39.61_-121.82_2026-02-01.csv"' in r.headers["content-disposition"]
    assert not r.text.startswith("#"), "Excel would show a comment line as data"


def test_header_and_one_row_per_day_with_iso_dates():
    header, rows = _rows(DURHAM)
    assert header == HEADER
    as_of = date.fromisoformat(DURHAM["as_of"])
    assert len(rows) == (as_of - START).days + 1
    days = [date.fromisoformat(r["date"]) for r in rows]          # raises if not ISO YYYY-MM-DD
    assert days == [START + timedelta(days=i) for i in range(len(rows))]


def test_last_running_total_matches_estimate():
    _, rows = _rows(DURHAM)
    chill = client.get("/estimate", params={**DURHAM, "history_seasons": 1}).json()["chill"]
    last = rows[-1]
    # /estimate rounds to 1 decimal; the file keeps 2 decimals for portions, so allow half a tenth.
    assert abs(float(last[f"chill_portions_{SINCE}"]) - chill["chill_portions"]) <= 0.05 + 1e-9
    assert float(last[f"chill_hours_32_45_{SINCE}"]) == chill["chill_hours"]
    assert float(last[f"hours_at_or_below_45_{SINCE}"]) == chill["hours_lt_45"]
    assert abs(float(last[f"utah_units_{SINCE}"]) - chill["utah_units"]) <= 0.05 + 1e-9
    assert sum(int(r["hours_missing"]) for r in rows) == chill["hours_missing"]


def test_daily_amounts_add_up_to_the_running_total():
    _, rows = _rows(DURHAM)
    for m in MEASURES:
        added = sum(float(r[f"{m}_day"]) for r in rows)
        assert abs(added - float(rows[-1][f"{m}_{SINCE}"])) < 1e-6, m


def test_after_season_end_stops_at_season_end_like_estimate():
    _, rows = _rows({**DURHAM, "as_of": "2026-05-01"})
    est = client.get("/estimate", params={**DURHAM, "as_of": "2026-05-01", "history_seasons": 1}).json()
    assert rows[-1]["date"] == est["chill"]["end"]


def test_day_with_no_hours_keeps_the_total_and_counts_24_missing():
    """E.g. today, before any station has reported: nothing added, every hour missing."""
    hours = pd.date_range("2025-09-01 01:00", "2025-09-02 23:00", freq="h")   # starts 1am, like CIMIS
    est = pd.Series(40.0, index=hours)
    est.iloc[5] = float("nan")                                                 # Sept 1, 6am left blank
    table = daily_chill_table(est, date(2025, 9, 1), date(2025, 9, 3))
    assert list(table["hours_missing"]) == [1, 0, 24]                         # the 1am start isn't a gap
    col = f"chill_hours_32_45_{SINCE}"
    assert list(table["chill_hours_32_45_day"]) == [22, 24, 0]
    assert table[col].iloc[-1] == table[col].iloc[-2] == 46


def test_unknown_variety_is_a_plain_404():
    r = client.get("/daily.csv", params={**DURHAM, "variety": "Banana"})
    assert r.status_code == 404
    assert "Unknown variety" in r.json()["detail"]
