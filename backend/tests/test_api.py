"""End-to-end checks on synthetic data (no CIMIS key or internet needed)."""
import os

os.environ["DATA_SOURCE"] = "synthetic"

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def test_health():
    assert client.get("/health").json()["ok"] is True


def test_varieties_has_a_crop_note_for_every_crop():
    body = client.get("/varieties").json()
    for crop in body["crop_order"]:
        assert body["crop_context"][crop], f"missing long-view note for {crop}"
    assert "Zhang et al. 2021" in body["climate_caption"]


def test_estimate_durham_replay():
    r = client.get("/estimate", params={"lat": 39.61, "lon": -121.82, "as_of": "2026-02-01",
                                       "exclude": ["12"], "history_seasons": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chill"]["chill_portions"] > 0
    assert "12" not in [n["station_id"] for n in body["neighbors"]]
    assert body["projection"]["method"].startswith("climatology")
    assert len(body["history"]["seasons"]) == 3


def test_validate_durham():
    r = client.get("/validate", params={"station_id": "12", "as_of": "2025-02-28"})
    assert r.status_code == 200, r.text
    v = r.json()["with_elevation_adjustment"]
    assert v["hours_compared"] > 1000
    assert "chill_portions" in v["error"]


def test_gdd_not_started_before_bloom():
    r = client.get("/estimate", params={"lat": 39.61, "lon": -121.82, "as_of": "2026-02-01",
                                       "exclude": ["12"], "history_seasons": 1})
    g = r.json()["gdd"]
    assert g["started"] is False and g["total_c_days"] == 0


def test_gdd_after_bloom():
    r = client.get("/estimate", params={"lat": 38.54, "lon": -121.78, "as_of": "2026-05-01",
                                       "history_seasons": 1})
    g = r.json()["gdd"]
    assert g["started"] is True and g["total_c_days"] > 0


def test_estimate_has_glance_fields():
    r = client.get("/estimate", params={"lat": 39.61, "lon": -121.82, "as_of": "2026-02-01",
                                       "variety": "Chandler walnut", "exclude": ["12"], "history_seasons": 3})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["summary"].startswith("Your Chandler walnut trees have")
    assert b["verdict"]["band"] in ("low", "normal", "high")
    assert b["target"]["target_cp"] == 50
    assert b["chill"]["start"] == "2025-09-01"


def test_decision_pistachio():
    """The Kern demo pin (config.DEMO_ORCHARDS), with its hold-out hidden, mid-January."""
    kern = config.DEMO_ORCHARDS["kern"]
    r = client.get("/decision", params={"lat": kern["lat"], "lon": kern["lon"], "as_of": "2026-01-15",
                                       "variety": kern["variety"], "exclude": [kern["holdout_station"]],
                                       "history_seasons": 4})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] in ("on_track", "watch", "at_risk", "done")
    assert d["target_date"] == "2026-03-02"
    assert d["decision_window"]["milestone_cp"] == 55
    assert "PCA" in d["pca_handoff"]


def test_unknown_variety_is_404():
    r = client.get("/decision", params={"lat": 35.62, "lon": -119.69, "variety": "Banana"})
    assert r.status_code == 404


def test_history_has_trend():
    r = client.get("/history", params={"lat": 39.61, "lon": -121.82, "as_of": "2026-02-01", "max_seasons": 6})
    assert r.status_code == 200, r.text
    h = r.json()
    assert len(h["seasons"]) >= 5 and h["trend_cp_per_decade"] is not None
