"""Season windows and labels."""
from app import seasons


def test_season_label_is_written_the_way_the_app_shows_it():
    assert seasons.season_label(2024) == "2024-25"
    assert seasons.season_label(1999) == "1999-00"
