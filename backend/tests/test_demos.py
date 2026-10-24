"""The demo orchards and the winters they need, checked on synthetic data (no key or internet needed)."""
import importlib.util
import inspect
import os
from datetime import date
from pathlib import Path

os.environ["DATA_SOURCE"] = "synthetic"

import pytest  # noqa: E402

from app import config, data, main  # noqa: E402


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
