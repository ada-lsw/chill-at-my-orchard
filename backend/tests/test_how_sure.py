"""How sure we are, in plain words: numbers from the 19-winter hold-out table (pitch/validation.csv).

The constants in config.py are copied from that table; these tests recompute them from the CSV so they
can't drift when someone reruns scripts/validation_table.py.
"""
import csv
import os
from pathlib import Path

os.environ.setdefault("DATA_SOURCE", "synthetic")

from fastapi.testclient import TestClient  # noqa: E402

from app import config, decision  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
VALIDATION_CSV = Path(__file__).resolve().parents[2] / "pitch" / "validation.csv"
MODEL_NAMES = ("dynamic", "utah", "idw", "inverse distance", "interpolat", "lapse", "rmse", "mae")


def shipped_rows() -> list[dict]:
    """Rows of pitch/validation.csv for the setting the app ships with."""
    with open(VALIDATION_CSV, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["setting"] == config.HOW_SURE_SETTING]
    assert rows, f"no rows for setting {config.HOW_SURE_SETTING!r}"
    return rows


def misses(station: str | None = None) -> list[float]:
    """Size of each winter's chill-portion error, for one station or (None) all."""
    return [abs(float(r["error_cp"])) for r in shipped_rows() if station in (None, r["station"])]


def test_shipped_setting_matches_config():
    neighbors, elevation = config.NEIGHBORS, "off" if config.LAPSE_F_PER_M == 0 else "on"
    assert config.HOW_SURE_SETTING == f"elevation {elevation}, {neighbors} neighbors, caps on"


def test_typical_miss_per_station_matches_csv():
    for station, typical in config.HOW_SURE_TYPICAL_MISS_CP.items():
        m = misses(station)
        assert typical == round(sum(m) / len(m), 2), station
        assert config.HOW_SURE_WINTERS[station] == len(m), station


def test_combined_numbers_match_csv():
    m = misses()
    assert config.HOW_SURE_TYPICAL_MISS_ALL_CP == round(sum(m) / len(m), 2)
    assert config.HOW_SURE_WINTERS_ALL == len(m) == sum(config.HOW_SURE_WINTERS.values())
    assert config.HOW_SURE_WORST_MISS_CP == max(m)


def test_winters_within_rounded_miss_matches_csv():
    x = decision.round_to_half(config.HOW_SURE_TYPICAL_MISS_ALL_CP)
    assert config.HOW_SURE_WINTERS_WITHIN == sum(e <= x for e in misses())


def test_kern_too_high_count_matches_csv():
    errors = [float(r["error_cp"]) for r in shipped_rows() if r["station"] == "5"]
    assert config.HOW_SURE_KERN_TOO_HIGH == sum(e > 0 for e in errors)


def test_round_to_half():
    assert decision.round_to_half(3.52) == 3.5
    assert decision.round_to_half(2.43) == 2.5
    assert decision.round_to_half(4.2) == 4.0
    assert decision.half_words(3.5) == "3½"
    assert decision.half_words(4.0) == "4"


def test_how_sure_line_is_one_plain_sentence():
    line = decision.how_sure_line()
    assert "\n" not in line and line.endswith(".") and line.count(". ") == 0
    assert not any(name in line.lower() for name in MODEL_NAMES), line
    assert "usually within about 3½ chill portions" in line
    assert "12 of 19 winters at 2 stations" in line


def test_estimate_includes_how_sure():
    r = client.get("/estimate", params={"lat": 39.61, "lon": -121.82, "as_of": "2026-02-01",
                                       "exclude": ["12"], "history_seasons": 1})
    assert r.status_code == 200, r.text
    assert r.json()["how_sure"] == decision.how_sure_line()


def test_glossary_has_per_station_line():
    line = client.get("/glossary").json()["measures"]["how_sure_by_station"]
    assert "2.4" in line and "4.5" in line and "10.4" in line
