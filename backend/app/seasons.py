"""Season windows. Chill and GDD are running totals, so everything needs a start date."""
from __future__ import annotations

from datetime import date, timedelta

from . import config

# Chill counting stops here (month, day) for season-total comparisons.
CHILL_END = (3, 31)


def chill_season_start(as_of: date) -> date:
    m, d = config.CHILL_START
    start = date(as_of.year, m, d)
    return start if as_of >= start else date(as_of.year - 1, m, d)


def chill_window(as_of: date) -> tuple[date, date, bool]:
    """(start, end, season_complete). End is capped at the season end."""
    start = chill_season_start(as_of)
    season_end = date(start.year + 1, *CHILL_END)
    return start, min(as_of, season_end), as_of > season_end


def gdd_window(as_of: date) -> tuple[date, date, bool]:
    """(start, end, started). GDD counts from bloom; before this year's bloom it hasn't started."""
    m, d = config.GDD_START
    start = date(as_of.year, m, d)
    return start, as_of, as_of >= start


def same_window_in(year_offset: int, start: date, end: date) -> tuple[date, date]:
    """Shift a window back N years (keeps day-of-season aligned; Feb 29 -> Feb 28)."""
    def shift(d: date) -> date:
        try:
            return d.replace(year=d.year - year_offset)
        except ValueError:
            return d.replace(year=d.year - year_offset, day=28)
    return shift(start), shift(end)


def plus_days(d: date, n: int) -> date:
    return d + timedelta(days=n)
