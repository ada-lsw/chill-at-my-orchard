"""The demo orchards: each one works with its hold-out station hidden, its pin sits on that station,
and the winters it shows get cached. Checked on synthetic data (no key or internet needed)."""
import importlib.util
import inspect
import os
from datetime import date
from pathlib import Path

os.environ["DATA_SOURCE"] = "synthetic"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config, data, interp, main  # noqa: E402
from tests.test_neighbors import fake_key  # noqa: E402,F401  shared fixture: a fake CIMIS key

client = TestClient(main.app)
DEMOS = sorted(config.DEMO_ORCHARDS)


def demo_params(demo: dict, exclude: list[str] | None = None) -> dict:
    """A demo's query with a short history to keep CI quick. By default the hold-out station is hidden
    (the accuracy proof's scenario); pass `exclude` to send what the picker sends instead."""
    hidden = [demo["holdout_station"]] if exclude is None else exclude
    return {"lat": demo["lat"], "lon": demo["lon"], "as_of": demo["as_of"], "variety": demo["variety"],
            "exclude": hidden, "history_seasons": 3}


def picker_exclude(demo: dict) -> list[str]:
    """What the picker hides for a demo button: the hold-out station only if the demo says to hide it."""
    return [demo["holdout_station"]] if demo["hide_in_demo"] else []


@pytest.fixture
def neighbor_spy(monkeypatch):
    """Every station the app picks as a neighbor, in any window, while the test runs.

    /decision doesn't list its neighbors, so this wraps main.estimate_at to see them.
    """
    used = []
    real_estimate_at = main.estimate_at

    def spy(*args, **kwargs):
        """main.estimate_at, also recording the neighbors it picked."""
        est, neighbors = real_estimate_at(*args, **kwargs)
        used.extend(neighbors["station_id"])
        return est, neighbors

    monkeypatch.setattr(main, "estimate_at", spy)
    return used


@pytest.mark.parametrize("key", DEMOS)
def test_demo_runs_without_its_holdout(key, neighbor_spy):
    """Guard test: both demo endpoints answer, never use the hidden station, and keep the variety.

    It passes before and after the Kern pin change, so it guards the demos; it doesn't prove the fix.
    """
    demo = config.DEMO_ORCHARDS[key]
    hidden = demo["holdout_station"]
    est = client.get("/estimate", params=demo_params(demo))
    dec = client.get("/decision", params=demo_params(demo))
    assert est.status_code == 200, est.text
    assert dec.status_code == 200, dec.text
    shown = [n["station_id"] for n in est.json()["neighbors"]]
    assert shown and hidden not in shown                  # neighbors listed, never the hidden one
    assert neighbor_spy and hidden not in neighbor_spy    # nor in any window of either endpoint
    assert est.json()["target"]["variety"] == demo["variety"]
    assert dec.json()["variety"] == demo["variety"]       # /decision has variety at the top level


def test_each_demo_says_whether_it_hides_its_station():
    """Both demo buttons hide their hold-out station, as the Kern label says ("station hidden to test the
    estimate", PR #25) and as the app has always done; config.py now says so too (Ada, Oct 24 12:38pm)."""
    assert config.DEMO_ORCHARDS["durham"]["hide_in_demo"] is True
    assert config.DEMO_ORCHARDS["kern"]["hide_in_demo"] is True
    assert "hidden" in config.DEMO_ORCHARDS["kern"]["label"]


@pytest.mark.parametrize("key", DEMOS)
def test_picker_rule_hides_each_demo_station(key):
    """With the picker's rule, each demo request hides its own station and never uses it as a neighbor."""
    demo = config.DEMO_ORCHARDS[key]
    r = client.get("/estimate", params=demo_params(demo, picker_exclude(demo)))
    assert r.status_code == 200, r.text
    assert r.json()["excluded"] == [demo["holdout_station"]]
    assert demo["holdout_station"] not in [n["station_id"] for n in r.json()["neighbors"]]


@pytest.mark.parametrize("key", DEMOS)
def test_demo_pin_sits_on_its_holdout_station(key):
    """The hold-out proof (/validate for the hidden station) measures the error at the demo's own spot."""
    demo = config.DEMO_ORCHARDS[key]
    station = data.get_stations().set_index("station_id").loc[demo["holdout_station"]]
    km = float(interp.haversine_km(demo["lat"], demo["lon"], station.lat, station.lon))
    # 1 km is a test tolerance for coordinate rounding (Durham's pin is ~0.4 km from its station),
    # not a model setting.
    assert km <= 1.0, f"{key} pin is {km:.1f} km from station {demo['holdout_station']}"


@pytest.fixture(scope="module")
def warm_cache():
    """scripts/warm_cache.py loaded as a module. Loading it doesn't run main()."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "warm_cache.py"
    spec = importlib.util.spec_from_file_location("warm_cache", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_history_default_comes_from_config():
    """The number of past winters the app compares against lives in one place."""
    for endpoint in (main.estimate, main.decision_endpoint):
        assert inspect.signature(endpoint).parameters["history_seasons"].default == config.HISTORY_SEASONS


def test_warm_cache_covers_every_winter_the_demo_asks_for(warm_cache):
    """A demo replaying Feb 1, 2026 (the 2025-26 winter) reaches back HISTORY_SEASONS winters
    (to 2015-16 with 10), and caching runs on through today's winter (2026-27 on Oct 24, 2026)."""
    expected = list(range(2025 - config.HISTORY_SEASONS, 2026 + 1))
    assert warm_cache.seasons_to_cache(date(2026, 2, 1), date(2026, 10, 24)) == expected


def test_warm_cache_pauses_before_a_current_season_refresh(warm_cache, monkeypatch):
    """A cached current season can still be re-downloaded (it refreshes daily), so warm_cache waits
    first. A finished season that is cached can't trigger a request, so it doesn't wait."""
    sleeps = []
    monkeypatch.setattr(warm_cache.time, "sleep", sleeps.append)
    monkeypatch.setattr(data, "is_cached", lambda sid, year: True)
    monkeypatch.setattr(data, "season_coverage", lambda sid, year: 1.0)
    coverage = warm_cache.coverage_once(pause=7)
    this_season = data.season_year(date.today())
    coverage("SYN-A", this_season - 1)
    assert sleeps == []
    coverage("SYN-A", this_season)
    assert sleeps == [7]


def test_warm_cache_failed_line_names_station_and_season_but_not_the_key(warm_cache, fake_key,
                                                                         monkeypatch, capsys):
    """A season that fails to download prints which station and season failed, with the key hidden."""
    def refused(station_id, year):
        raise RuntimeError(f"CIMIS refused key {fake_key}")

    monkeypatch.setattr(data, "season_coverage", refused)
    monkeypatch.setattr(interp, "pin_elevation", lambda stations, lat, lon: (110.0, "test"))  # no internet
    demo = config.DEMO_ORCHARDS["kern"]
    failed = warm_cache.warm_demo("kern", demo, data.get_stations(), warm_cache.coverage_once(pause=0))
    printed = capsys.readouterr().out
    assert failed > 0 and "FAILED" in printed
    assert f"station {demo['holdout_station']}" in printed and "2025-26" in printed
    assert fake_key not in printed and "***" in printed
