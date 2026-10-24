"""scripts/validation_table.py: the 8 settings it tries, its summary math, how it picks the winner,
and that it never downloads. Runs on synthetic data, with no key or internet."""
import importlib.util
import math
import os
import sys
from pathlib import Path

os.environ["DATA_SOURCE"] = "synthetic"

import pytest  # noqa: E402

from app import config, data  # noqa: E402


@pytest.fixture(scope="module")
def vt():
    """scripts/validation_table.py loaded as a module. Loading it doesn't run main()."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "validation_table.py"
    spec = importlib.util.spec_from_file_location("validation_table", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["validation_table"] = module    # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def test_grid_is_exactly_the_eight_sourced_settings(vt):
    grid = vt.settings_grid()
    assert len(grid) == 8 and len(set(grid)) == 8
    assert {s.lapse_f_per_m for s in grid} == {0.0117, 0.0}          # 6.5 °C/km standard lapse, or none
    assert {s.neighbors for s in grid} == {5, 3}
    assert {(s.max_km, s.max_elev_m) for s in grid} == {(100.0, 300.0), (math.inf, math.inf)}
    assert vt.PREVIOUS in grid


def test_grid_does_not_move_when_config_changes(vt, monkeypatch):
    """The grid and the 'before this PR' setting are fixed, so shipping a winner can't relabel them."""
    before = vt.settings_grid()
    monkeypatch.setattr(config, "LAPSE_F_PER_M", 0.0)
    monkeypatch.setattr(config, "NEIGHBORS", 3)
    assert vt.settings_grid() == before
    assert (vt.PREVIOUS.lapse_f_per_m, vt.PREVIOUS.neighbors) == (0.0117, 5)


def test_summary_math(vt):
    s = vt.summarize([+1.0, -2.0, +3.0, 0.0])
    assert s["lean"] == pytest.approx(0.5)            # mean error
    assert s["typical_miss"] == pytest.approx(1.5)    # mean absolute error
    assert s["worst"] == 3.0                          # largest miss, sign kept
    assert (s["high"], s["low"], s["n"]) == (2, 1, 4)   # 0.0 is neither too high nor too low


def test_worst_keeps_the_sign_of_a_low_miss(vt):
    assert vt.summarize([1.0, -8.8, 2.0])["worst"] == -8.8


def test_within_counts_winters_inside_a_miss(vt):
    assert vt.within([0.5, -2.9, 3.1, -1.0], 3) == 3


def scored(vt, **mae_by_setting):
    """{Setting: {"typical_miss", "complete"}} from names like on_5_on=4.0 ('lapse_neighbors_caps');
    a trailing '_incomplete' marks a setting with uncached stations."""
    out = {}
    for key, mae in mae_by_setting.items():
        lapse, k, caps, *rest = key.split("_")
        setting = vt.Setting(0.0117 if lapse == "on" else 0.0, int(k), *(
            (100.0, 300.0) if caps == "on" else (math.inf, math.inf)))
        out[setting] = {"typical_miss": mae, "complete": not rest}
    return out


def test_winner_is_the_lowest_typical_miss_among_complete_settings(vt):
    winner, note = vt.pick_winner(scored(vt, on_5_on=4.01, off_3_on=3.52, on_3_off_incomplete=3.0))
    assert (winner.lapse_f_per_m, winner.neighbors, winner.max_km) == (0.0, 3, 100.0)
    assert note == ""


def test_a_tie_with_the_previous_setting_at_one_decimal_keeps_it(vt):
    winner, _ = vt.pick_winner(scored(vt, on_5_on=4.01, off_3_on=3.98))
    assert winner == vt.PREVIOUS


def test_an_exact_tie_prefers_fewer_changes(vt):
    """Caps on and caps off give the same miss at 3 neighbors: keep the caps as they were."""
    winner, _ = vt.pick_winner(scored(vt, on_5_on=4.01, off_3_off=3.52, off_3_on=3.52))
    assert winner.max_km == 100.0


def test_a_caps_off_winner_is_not_shipped_but_reported(vt):
    """Amendment D lets this PR change only the lapse rate and the neighbor count in config."""
    winner, note = vt.pick_winner(scored(vt, on_5_on=4.01, on_3_off=3.0, off_3_on=3.52))
    assert winner.max_km == 100.0 and (winner.lapse_f_per_m, winner.neighbors) == (0.0, 3)
    assert "DECISION FOR ADA" in note


def test_applied_restores_config_even_after_an_error(vt):
    saved = (config.LAPSE_F_PER_M, config.NEIGHBORS, config.MAX_NEIGHBOR_KM, config.MAX_ELEV_DIFF_M)
    with pytest.raises(RuntimeError):
        with vt.applied(vt.Setting(0.0, 3, math.inf, math.inf)):
            assert config.NEIGHBORS == 3 and config.MAX_NEIGHBOR_KM == math.inf
            raise RuntimeError("stop")
    assert (config.LAPSE_F_PER_M, config.NEIGHBORS, config.MAX_NEIGHBOR_KM, config.MAX_ELEV_DIFF_M) == saved


def test_holdout_row_never_downloads(vt, monkeypatch):
    """A station-season that isn't saved is recorded as uncached and skipped, never requested."""
    asked = []
    monkeypatch.setattr(data, "is_cached", lambda sid, year: False)
    monkeypatch.setattr(data, "season_hourly", lambda sid, year: asked.append(sid))
    monkeypatch.setattr(data, "season_coverage", lambda sid, year: asked.append(sid))
    uncached = set()
    row = vt.holdout_row(data.get_stations(), vt.PREVIOUS, "5", 2024, uncached)
    assert row is None and asked == []
    assert ("5", 2024) in uncached


def test_outputs_are_written_only_from_real_data(vt, monkeypatch):
    """A synthetic run must never overwrite the real numbers in pitch/."""
    monkeypatch.setattr(config, "DATA_SOURCE", "synthetic")
    with pytest.raises(SystemExit):
        vt.check_real_data()
