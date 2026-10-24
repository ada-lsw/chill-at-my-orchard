"""Rules behind the verdict band and decision card (no data fetching)."""
from datetime import date

from app import decision


def test_verdict_bands():
    past = list(range(10, 110, 10))          # 10, 20, ..., 100
    assert decision.verdict(5, past)["band"] == "low"
    assert decision.verdict(55, past)["band"] == "normal"
    assert decision.verdict(105, past)["band"] == "high"
    assert decision.verdict(55, [])["band"] == "unknown"


def test_verdict_color_always_has_a_word():
    v = decision.verdict(5, [10, 20, 30])
    assert v["band"] == "low" and v["color"] == "red"


def test_closest_season_picks_smallest_gap():
    past = [{"season": "2019-20", "curve": [0, 1, 2, 3, 9]},
            {"season": "2020-21", "curve": [0, 2, 4, 6, 9]}]
    assert decision.closest_season([0, 2, 4], past) == "2020-21"


def test_target_date_is_in_the_same_season():
    assert decision.target_date_for(date(2026, 2, 1)) == date(2026, 3, 2)
    assert decision.target_date_for(date(2025, 10, 15)) == date(2026, 3, 2)


def _scen(total_added, days=30):
    """A past season that added chill evenly up to `total_added` over `days` days."""
    return {"season": "x", "added_by_day": [total_added * i / (days - 1) for i in range(days)]}


def test_status_at_risk_on_track_and_done():
    low = [_scen(5)] * 8 + [_scen(20)] * 2          # 2 of 10 reach 57 from 45
    high = [_scen(20)] * 9 + [_scen(5)]             # 9 of 10 reach
    assert decision.decision(45, date(2026, 2, 1), "pistachio", 57, low)["status"] == "at_risk"
    assert decision.decision(45, date(2026, 2, 1), "pistachio", 57, high)["status"] == "on_track"
    assert decision.decision(60, date(2026, 2, 1), "pistachio", 57, low)["status"] == "done"


def test_decision_window_only_for_pistachio():
    scen = [_scen(20)] * 10
    p = decision.decision(45, date(2026, 2, 1), "pistachio", 57, scen)
    w = decision.decision(45, date(2026, 2, 1), "walnut", 57, scen)
    assert p["decision_window"]["likely_between"] is not None
    assert w["decision_window"] is None


def test_lines_never_name_a_product_rate_or_apply_date():
    scen = [_scen(5)] * 10
    d = decision.decision(45, date(2026, 2, 1), "pistachio", 57, scen)
    line = decision.decision_line(d).lower()
    assert "pca" in line
    for banned in ("apply", "spray on", "rate", "gallon", "cyanamide"):
        assert banned not in line


def test_progress_never_shows_100_before_the_target():
    assert decision.progress_pct(56.8, 57) == 99         # 99.6 would round to 100
    assert decision.progress_pct(57.2, 57) == 100
    assert decision.progress_pct(45, 57) == 79
    assert decision.progress_pct(10, 0) is None


def test_summary_never_says_57_above_the_57():
    """Just past the target: the rounded numbers are equal, so say "about" instead of "above"."""
    s = decision.summary_line("Kerman pistachio", 57.2, 57, "normal", "2020-21")
    assert "above the 57" not in s
    assert s.startswith("Your Kerman pistachio trees have reached their target: about the 57 chill portions they need.")


def test_summary_never_says_57_of_the_57_before_the_target():
    """Just short of the target: say "almost all" and a percent under 100."""
    for so_far in (56.6, 56.8):
        s = decision.summary_line("Kerman pistachio", so_far, 57, "normal", None)
        assert "57 of the 57" not in s and "(100%)" not in s
        assert "almost all of the 57 chill portions they need (99%)" in s


def test_summary_keeps_its_wording_away_from_the_target():
    """Guard test: the usual sentences are unchanged."""
    assert decision.summary_line("Kerman pistachio", 45, 57, "low", None).startswith(
        "Your Kerman pistachio trees have 45 of the 57 chill portions they need (79%).")
    assert decision.summary_line("Chandler walnut", 60, 50, "normal", "2016-17").startswith(
        "Your Chandler walnut trees have reached their target: 60 chill portions, above the 50 they need.")
