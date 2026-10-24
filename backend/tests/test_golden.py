"""Golden test: our daily chill hours vs FNRIC's, on real saved weather.  Owner: Backend B.

Station-winter: Shafter (5), 2024-25, Sept 1 to Feb 28. Shafter is the Kern demo pin, and both of its
files for that winter are saved: data/cache/hourly_cimis_5_2024.parquet (our CIMIS hours) and
data/cache/fnric_CIMIS-5.csv (FNRIC's daily chill). The test reads them straight from the repo's
data/cache/ (never downloads), and is skipped when either file isn't there, so CI stays green either way.

Chill portions are NOT tested here: their difference is recorded in pitch/golden.md, and a question
about our chill-portion model is under investigation separately.
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

from app import fnric

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "cache"
STATION, YEAR = "5", 2024      # Shafter, winter 2024-25
FILES = [CACHE / f"hourly_cimis_{STATION}_{YEAR}.parquet", CACHE / f"fnric_CIMIS-{STATION}.csv"]


@pytest.fixture(scope="module")
def gc():
    """scripts/golden_compare.py loaded as a module. Loading it doesn't run main()."""
    path = REPO / "scripts" / "golden_compare.py"
    spec = importlib.util.spec_from_file_location("golden_compare", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["golden_compare"] = module    # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def test_the_2400_reading_belongs_to_the_day_it_ends(gc):
    """CIMIS hours are hour-ending; data.py stores "Jan 5, 2400" as Jan 6 00:00. It must count for Jan 5."""
    stored = pd.Series(pd.to_datetime(["2025-01-05 01:00", "2025-01-05 23:00", "2025-01-06 00:00",
                                       "2025-01-06 01:00"]))
    days = gc.day_of(stored).dt.strftime("%Y-%m-%d").tolist()
    assert days == ["2025-01-05", "2025-01-05", "2025-01-05", "2025-01-06"]


@pytest.mark.skipif(not all(f.exists() for f in FILES), reason="Shafter 2024-25 isn't saved in data/cache/")
def test_shafter_daily_chill_hours_match_fnric_exactly(gc):
    """On every complete day (24 real readings in ours, a full FNRIC row), chill hours are equal.

    Observed when this test was written (pitch/golden.md): 180 complete days, all 180 equal. The one
    other day of the 181 has an hour our gap filler filled, so it isn't compared.
    """
    daily = fnric._parse(FILES[1].read_text())          # fnric.py's own parser, on the repo's file
    w = gc.compare_winter(CACHE, STATION, YEAR, daily)
    assert w is not None
    assert w.complete_days == 180                       # so the test can't pass by comparing fewer days
    assert w.exact_days == w.complete_days
