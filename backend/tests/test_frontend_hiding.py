"""The frontend hides the same station everywhere: the picker follows each demo's hide_in_demo setting, and the
long view asks /history without the hidden station, like the glance card does. Checked without a browser."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "frontend"))

from components import history_panel, picker  # noqa: E402


def test_picker_hides_a_demo_station_only_when_the_demo_says_so():
    """A demo that sets hide_in_demo False keeps its station; True or a shared link (no setting) hides it."""
    assert picker.hidden_stations({"holdout_station": "5", "hide_in_demo": True}) == ["5"]
    assert picker.hidden_stations({"holdout_station": "5", "hide_in_demo": False}) == []
    assert picker.hidden_stations({"holdout_station": "12"}) == ["12"]       # shared link: hide, as before
    assert picker.hidden_stations({"lat": 38.5, "lon": -121.7}) == []        # a dropped pin hides nothing


def test_long_view_hides_the_same_station_as_the_card(monkeypatch):
    """history_panel asks /history with the page's exclude list, so the long view never uses a hidden station."""
    calls = []

    def fake_get(path, **params):
        """Record the call and answer like /history with no saved winters (the panel then stops early)."""
        calls.append((path, params))
        return {"seasons": [], "trend_sentence": "No past winters with saved data here yet."}

    monkeypatch.setattr(history_panel, "get", fake_get)
    place = {"lat": 35.53, "lon": -119.28, "as_of": "2026-02-01", "exclude": ["5"]}
    history_panel.show(place, est={})
    path, params = calls[0]
    assert path == "/history"
    assert params["exclude"] == ["5"]
