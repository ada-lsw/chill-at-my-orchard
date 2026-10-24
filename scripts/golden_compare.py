"""Golden comparison: does our chill math give FNRIC's numbers on the same real weather?  Owner: Backend B.

Run from the repo root, offline, with saved data only (it never downloads):

    python scripts/golden_compare.py

For every station-winter saved BOTH ways (our CIMIS hourly file data/cache/hourly_cimis_<id>_<year>.parquet
and FNRIC's daily file data/cache/fnric_CIMIS-<id>.csv), winters 2016-17 to 2024-25, Sept 1 to Feb 28:

1. Daily chill hours (32°F < T <= 45°F): ours from chill.chill_hours on each day's 24 hourly readings,
   FNRIC's from its daily hours_32_45. Only COMPLETE days count: 24 real readings in ours (none missing,
   none filled by our gap filler) and a non-empty FNRIC row.
2. Season-to-date chill portions at Feb 28: ours from chill.chill_portions over the whole hourly series,
   FNRIC's as the sum of its daily portions_dynamic.
3. The 5 station-winters whose season chill-hour totals differ most, with the evidence for each.

Writes pitch/golden.md. The math is chill.py's, unchanged: this script only compares.

Which day an hourly reading belongs to: CIMIS times are hour-ending ("0100" to "2400"), and data.py stores
each reading at Date + Hour, so the "2400" reading of Jan 5 is stored as Jan 6 00:00. Here every reading
is assigned to the day it ENDS in: day = (stored time - 1 hour). So Jan 5 is the readings stored from
Jan 5 01:00 to Jan 6 00:00, the 24 hours CIMIS labels "Jan 5".
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app import chill, fnric, seasons  # noqa: E402

CACHE = REPO / "data" / "cache"
OUT_MD = REPO / "pitch" / "golden.md"
WINTERS = range(2016, 2025)          # season start years: 2016-17 to 2024-25
END_MONTH_DAY = (2, 28)              # compare Sept 1 to Feb 28 (Feb 29 left out in leap winters)
HOURS_PER_DAY = 24


# ---------------------------------------------------------------- which files exist

def hourly_path(cache: Path, station_id: str, year: int) -> Path:
    """Our saved CIMIS hourly file for one station and one season (Sept 1 to Aug 31)."""
    return cache / f"hourly_cimis_{station_id}_{year}.parquet"


def fnric_path(cache: Path, station_id: str) -> Path:
    """FNRIC's saved daily chill file for one station."""
    return cache / f"fnric_CIMIS-{station_id}.csv"


def saved_stations(cache: Path) -> tuple[set[str], set[str]]:
    """(stations with an FNRIC file, stations with at least one CIMIS hourly file), as CIMIS numbers."""
    with_fnric = {p.stem.removeprefix("fnric_CIMIS-") for p in cache.glob("fnric_CIMIS-*.csv")}
    with_hourly = {p.stem.split("_")[2] for p in cache.glob("hourly_cimis_*_*.parquet")}
    return with_fnric, with_hourly


def stations_in_both(cache: Path) -> list[str]:
    """CIMIS station numbers saved both ways, sorted as numbers."""
    with_fnric, with_hourly = saved_stations(cache)
    return sorted(with_fnric & with_hourly, key=int)


def window(year: int) -> tuple[date, date]:
    """Sept 1 of the season's start year to Feb 28 of the next year, both included."""
    return date(year, 9, 1), date(year + 1, *END_MONTH_DAY)


# ---------------------------------------------------------------- our hourly data, by day

def read_hourly_file(path: Path) -> pd.DataFrame:
    """datetime, temp_F, is_filled from one saved season file (an empty season file has no dates)."""
    df = pd.read_parquet(path, columns=["datetime", "temp_F", "is_filled"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["temp_F"] = df["temp_F"].astype(float)
    df["is_filled"] = df["is_filled"].astype(bool)
    return df


def day_of(stored: pd.Series) -> pd.Series:
    """The day each hour-ending reading belongs to: stored time minus 1 hour, at midnight.

    Jan 5 01:00 to Jan 6 00:00 (CIMIS "Jan 5, 0100" to "Jan 5, 2400") all belong to Jan 5.
    """
    return (stored - pd.Timedelta(hours=1)).dt.normalize()


def load_hourly(cache: Path, station_id: str, year: int) -> pd.DataFrame:
    """Our hourly readings for the window, each with the day it belongs to (hour-ending rule above).

    Columns: datetime, temp_F, is_filled, day. Empty if the season isn't saved.
    """
    path = hourly_path(cache, station_id, year)
    if not path.exists():
        return pd.DataFrame(columns=["datetime", "temp_F", "is_filled", "day"])
    df = read_hourly_file(path)
    df["day"] = day_of(df["datetime"])
    start, end = window(year)
    inside = (df["day"] >= pd.Timestamp(start)) & (df["day"] <= pd.Timestamp(end))
    return df[inside].sort_values("datetime").reset_index(drop=True)


def day_chill_hours(temps_f: pd.Series) -> float:
    """One day's chill hours with chill.py's own function (its running total at the day's last hour)."""
    return float(chill.chill_hours(temps_f)[-1]) if len(temps_f) else 0.0


def ours_by_day(hourly: pd.DataFrame, year: int) -> pd.DataFrame:
    """One row per day of the window: readings (non-missing), filled (by our gap filler), chill_hours.

    A day with no hourly rows at all has readings 0 and chill_hours 0.
    """
    days = pd.date_range(*window(year), freq="D")
    if hourly.empty:
        return pd.DataFrame({"readings": 0, "filled": 0, "chill_hours": 0.0}, index=days)
    g = hourly.groupby("day")
    out = pd.DataFrame({
        "readings": g["temp_F"].count(),
        "filled": g["is_filled"].sum(),
        "chill_hours": g["temp_F"].apply(day_chill_hours),
    })
    return out.reindex(days).fillna({"readings": 0, "filled": 0, "chill_hours": 0.0})


def fnric_by_day(daily: pd.DataFrame, year: int) -> pd.DataFrame:
    """FNRIC's complete rows inside the window, indexed by day (a day with empty values is left out)."""
    start, end = window(year)
    inside = daily[(daily["Date"] >= pd.Timestamp(start)) & (daily["Date"] <= pd.Timestamp(end))]
    complete = inside[inside[fnric.COLUMNS].notna().all(axis=1)]
    return complete.set_index("Date")[fnric.COLUMNS]


# ---------------------------------------------------------------- one station-winter

@dataclass
class Winter:
    """Everything the report needs about one station-winter."""
    station_id: str
    year: int
    days_in_window: int
    complete_days: int            # 24 real readings in ours and a non-empty FNRIC row
    exact_days: int               # complete days where daily chill hours are equal
    fnric_zero_rows: int          # complete days that differ where FNRIC's row is 0 in all four columns
    fnric_missing_days: int       # window days with no complete FNRIC row
    ours_missing_hours: int       # window hours with no temperature in ours (absent or empty)
    ours_filled_hours: int        # window hours our gap filler filled (<= 3-hour gaps)
    ch_ours: float                # season chill hours, ours, all hours we have
    ch_fnric: float               # season chill hours, FNRIC, all rows it has
    ch_diff_complete_days: float  # ours - FNRIC, summed over complete days only
    ch_ours_on_fnric_missing: float   # our chill hours on days FNRIC has no row
    cp_ours: float                # chill portions at Feb 28, ours
    cp_fnric: float               # chill portions at Feb 28, FNRIC (sum of daily)

    @property
    def label(self) -> str:
        return seasons.season_label(self.year)

    @property
    def ch_diff(self) -> float:
        return self.ch_ours - self.ch_fnric

    @property
    def cp_diff(self) -> float:
        return self.cp_ours - self.cp_fnric


def compare_winter(cache: Path, station_id: str, year: int, daily_fnric: pd.DataFrame) -> Winter | None:
    """Compare one station-winter. None if either source has no data in the window."""
    hourly = load_hourly(cache, station_id, year)
    theirs = fnric_by_day(daily_fnric, year)
    if hourly["temp_F"].notna().sum() == 0 or theirs.empty:
        return None
    ours = ours_by_day(hourly, year)
    ours_complete = (ours["readings"] == HOURS_PER_DAY) & (ours["filled"] == 0)
    both = ours.index[ours_complete & ours.index.isin(theirs.index)]
    diff = ours.loc[both, "chill_hours"] - theirs.loc[both, "hours_32_45"]
    fnric_missing = ours.index[~ours.index.isin(theirs.index)]
    return Winter(
        station_id=station_id, year=year, days_in_window=len(ours),
        complete_days=len(both), exact_days=int((diff == 0).sum()),
        fnric_zero_rows=int((theirs.loc[diff.index[diff != 0], fnric.COLUMNS] == 0).all(axis=1).sum()),
        fnric_missing_days=len(fnric_missing),
        ours_missing_hours=int(len(ours) * HOURS_PER_DAY - ours["readings"].sum()),
        ours_filled_hours=int(ours["filled"].sum()),
        ch_ours=float(ours["chill_hours"].sum()), ch_fnric=float(theirs["hours_32_45"].sum()),
        ch_diff_complete_days=float(diff.sum()),
        ch_ours_on_fnric_missing=float(ours.loc[fnric_missing, "chill_hours"].sum()),
        cp_ours=float(chill.chill_portions(hourly["temp_F"])[-1]),
        cp_fnric=float(theirs["portions_dynamic"].sum()),
    )


def compare_all(cache: Path = CACHE) -> list[Winter]:
    """Every station-winter saved both ways, in station then winter order."""
    rows = []
    for sid in stations_in_both(cache):
        daily = fnric._parse(fnric_path(cache, sid).read_text())   # fnric.py's own parser and checks
        for year in WINTERS:
            w = compare_winter(cache, sid, year, daily)
            if w is not None:
                rows.append(w)
    return rows


# ---------------------------------------------------------------- the report

def explain(w: Winter) -> str:
    """Where a season chill-hour difference comes from, in numbers. Only a part the numbers pin down gets a cause.

    The season difference splits exactly into three parts: complete days, our chill on days FNRIC has no
    row for, and days incomplete in ours (missing or filled hours). The complete-day part stays "unexplained".
    """
    differing = w.complete_days - w.exact_days
    on_incomplete = w.ch_diff - w.ch_diff_complete_days - w.ch_ours_on_fnric_missing
    facts = (f"FNRIC missing days: {w.fnric_missing_days}; our missing hours: {w.ours_missing_hours}, "
             f"our filled hours: {w.ours_filled_hours}; complete days that differ: {differing}"
             + (f" (on {w.fnric_zero_rows} of them FNRIC's row is 0 in all four columns)" if differing else ""))
    split = []
    if w.ch_diff_complete_days:
        split.append(f"{w.ch_diff_complete_days:+.0f} h on complete days: unexplained")
    if w.ch_ours_on_fnric_missing:
        split.append(f"{w.ch_ours_on_fnric_missing:+.0f} h on days FNRIC has no row for (FNRIC data gap)")
    if on_incomplete:
        split.append(f"{on_incomplete:+.0f} h on days with missing or filled hours in ours")
    return facts + ". **" + "; ".join(split or ["no difference"]) + "**"


def cp_row(name: str, diffs: np.ndarray) -> str:
    """One table row: mean, median and 10th-90th percentile of ours minus FNRIC, chill portions."""
    if not len(diffs):
        return f"| {name} | n/a | n/a | n/a |"
    p10, p90 = np.percentile(diffs, [10, 90])
    return f"| {name} | {diffs.mean():+.2f} | {np.median(diffs):+.2f} | {p10:+.2f} to {p90:+.2f} |"


def pct(a: float, b: float) -> str:
    """a as a percent of b, one decimal."""
    return f"{100 * a / b:.1f}%" if b else "n/a"


def report(rows: list[Winter], other_rule_share: str) -> str:
    """pitch/golden.md as text."""
    complete = sum(w.complete_days for w in rows)
    exact = sum(w.exact_days for w in rows)
    stations = sorted({w.station_id for w in rows}, key=int)
    winters = sorted({w.year for w in rows})
    cp = np.array([w.cp_diff for w in rows])
    full = [w for w in rows if w.complete_days == w.days_in_window]
    no_overlap = sorted(set(stations_in_both(CACHE)) - set(stations), key=int)
    with_fnric, with_hourly = saved_stations(CACHE)
    fnric_only = sorted(with_fnric - with_hourly, key=int)
    sentence = (f"Our daily chill hours match FNRIC's exactly on {pct(exact, complete)} of {complete:,} complete "
                f"station-days across {len(stations)} stations and {len(winters)} winters "
                f"({seasons.season_label(winters[0])} to {seasons.season_label(winters[-1])}).")
    lines = [
        "# Golden test: our chill vs FNRIC's (PRELIMINARY, until Ada reviews)",
        "",
        "Made by `python scripts/golden_compare.py` from the saved data in `data/cache/` (no downloads). "
        "Window: Sept 1 to Feb 28 of each winter. Math: `backend/app/chill.py`, unchanged.",
        "",
        "## Pitch sentence (PRELIMINARY)",
        "",
        f"> {sentence}",
        "",
        "## Daily chill hours (32°F < T ≤ 45°F)",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Stations compared | {len(stations)} ({', '.join(stations)}) |",
        f"| Station-winters compared | {len(rows)} |",
        f"| Complete station-days | {complete:,} |",
        f"| Days that match exactly | {exact:,} ({pct(exact, complete)}) |",
        f"| Days that differ | {complete - exact:,} |",
        "",
        (f"Stations {', '.join(no_overlap)} have both files but no data from both sources in these winters, "
         "so they are not counted. " if no_overlap else "")
        + (f"Stations {', '.join(fnric_only)} have an FNRIC file but no CIMIS hourly file saved, so they are "
           "not counted either." if fnric_only else ""),
        "",
        "A complete day has 24 real hourly readings in our CIMIS data (none missing, none filled by our "
        "gap filler) and a non-empty row in FNRIC's daily file. CIMIS times are hour-ending; each reading "
        "is counted in the day it ends in, so the 24:00 reading belongs to the day it closes (stored by "
        "`data.py` as 00:00 of the next day). "
        f"Check of that rule: counting the 24:00 reading in the next day instead matches on {other_rule_share} "
        "of the same days.",
        "",
        "## Chill portions at Feb 28 (season to date)",
        "",
        "| Station-winters | Mean | Median | 10th to 90th percentile |",
        "|---|---|---|---|",
        cp_row(f"All {len(rows)} station-winters", cp),
        cp_row(f"The {len(full)} station-winters where every day is complete both ways",
               np.array([w.cp_diff for w in full])),
        "",
        "Ours is `chill.chill_portions` over the hourly series "
        "(missing hours carried forward, as chill.py does); FNRIC's is the sum of its daily "
        "`portions_dynamic`. The golden test asserts nothing about chill portions. A known one-hour-step "
        "question in our chill-portion model is under investigation separately; no claim is made here "
        "about the cause of this difference.",
        "",
        "## Biggest season chill-hour differences (top 5 station-winters)",
        "",
        "| Station | Winter | Ours (h) | FNRIC (h) | Ours minus FNRIC | Evidence |",
        "|---|---|---|---|---|---|",
    ]
    for w in sorted(rows, key=lambda w: abs(w.ch_diff), reverse=True)[:5]:
        lines.append(f"| {w.station_id} | {w.label} | {w.ch_ours:.0f} | {w.ch_fnric:.0f} | "
                     f"{w.ch_diff:+.0f} | {explain(w)} |")
    lines += [
        "",
        "Season totals use every hour and row each side has: our missing hours count 0 (as in the app), "
        "and FNRIC's missing days count 0. The parts of the difference add up: complete days, plus our "
        "chill on FNRIC's missing days, plus days incomplete in ours.",
        "",
        "## All station-winters",
        "",
        "| Station | Winter | Complete days | Exact | FNRIC missing days | Our missing h | Our filled h | "
        "Chill hours ours / FNRIC | Chill portions ours / FNRIC |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for w in rows:
        lines.append(f"| {w.station_id} | {w.label} | {w.complete_days} | {w.exact_days} | "
                     f"{w.fnric_missing_days} | {w.ours_missing_hours} | {w.ours_filled_hours} | "
                     f"{w.ch_ours:.0f} / {w.ch_fnric:.0f} | {w.cp_ours:.1f} / {w.cp_fnric:.1f} |")
    return "\n".join(lines) + "\n"


def other_rule_share(cache: Path, rows: list[Winter]) -> str:
    """Match share if the 24:00 reading went to the NEXT day (hour-beginning). A check, not used above."""
    exact = total = 0
    for sid in sorted({w.station_id for w in rows}, key=int):
        daily = fnric._parse(fnric_path(cache, sid).read_text())
        for w in (w for w in rows if w.station_id == sid):
            path = hourly_path(cache, sid, w.year)
            df = read_hourly_file(path)
            df["day"] = df["datetime"].dt.normalize()
            ours = ours_by_day(df[df["day"].between(*map(pd.Timestamp, window(w.year)))], w.year)
            theirs = fnric_by_day(daily, w.year)
            ok = ours.index[(ours["readings"] == HOURS_PER_DAY) & (ours["filled"] == 0)
                            & ours.index.isin(theirs.index)]
            exact += int((ours.loc[ok, "chill_hours"] == theirs.loc[ok, "hours_32_45"]).sum())
            total += len(ok)
    return f"{pct(exact, total)} of {total:,}"


def main() -> None:
    rows = compare_all(CACHE)
    if not rows:
        sys.exit("No station-winter is saved both ways in data/cache/; nothing to compare.")
    OUT_MD.write_text(report(rows, other_rule_share(CACHE, rows)))
    print(OUT_MD.read_text())


if __name__ == "__main__":
    main()
