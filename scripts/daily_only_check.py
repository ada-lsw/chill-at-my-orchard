"""Daily-only check: how much chill do we lose if a station only kept each day's high and low?

Julia Stover's ask: "hourly temperatures rebuilt from daily data". For the two hold-out stations
(Durham 12, winters 2016-17 to 2024-25; Shafter 5, winters 2016-17 to 2025-26), with saved data only:

1. take the REAL hourly temperatures (data/cache/, no downloads);
2. work out each day's low and high (only from days with all 24 hours);
3. rebuild hourly temperatures from just those two numbers (app.hourly_from_daily, the chillR method);
4. count chill Sept 1 to Feb 28 on both, over the same hours (an hour missing in either is left out
   of both), with chill.summarize;
5. report rebuilt minus real for chill portions, chill hours and Utah units, per winter, plus the
   typical (mean absolute) and worst difference.

Writes pitch/daily_only.md. Run from the repo root:

    CIMIS_APP_KEY= DATA_SOURCE=cimis python scripts/daily_only_check.py
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
os.environ.setdefault("DATA_SOURCE", "cimis")

import pandas as pd  # noqa: E402

from app import chill, data, seasons  # noqa: E402
from app import hourly_from_daily as hfd  # noqa: E402

HOLDOUTS = {"12": range(2016, 2025), "5": range(2016, 2026)}   # season start years, as validation_table.py
NAMES = {"12": "Durham (12)", "5": "Shafter (5), the Kern pin"}
MEASURES = [("chill_portions", "chill portions", 1), ("chill_hours", "chill hours", 0),
            ("utah_units", "Utah units", 0)]
OUT_MD = REPO / "pitch" / "daily_only.md"


def saved_hours(station_id: str, year: int) -> pd.Series | None:
    """Real hourly °F for one winter plus the day on each side, from saved files only; None if not saved.

    The day before Sept 1 and after Feb 28 give the rebuilt curve its first night and last evening.
    """
    if not data.is_cached(station_id, year):
        return None
    years = [y for y in (year - 1, year) if data.is_cached(station_id, y)]
    df = pd.concat([data.season_hourly(station_id, y) for y in years], ignore_index=True)
    s = df.set_index("datetime")["temp_F"].astype(float).sort_index()
    return s[~s.index.duplicated()]


def compare_winter(station_id: str, year: int, latitude: float) -> dict | None:
    """Chill from real hours vs hours rebuilt from daily low/high, Sept 1 to Feb 28, same hours."""
    real = saved_hours(station_id, year)
    if real is None:
        return None
    start, end, _ = seasons.chill_window(date(year + 1, 2, 28))
    lo, hi = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)   # same slice as data.get_hourly
    daily = hfd.daily_min_max(real)
    daily = daily[(daily.index >= lo - pd.Timedelta(days=1)) & (daily.index <= hi)]
    rebuilt = hfd.make_hourly_temps(daily, latitude)
    clock = pd.date_range(lo, hi, freq="h", inclusive="left")
    real_w, rebuilt_w = real.reindex(clock), rebuilt.reindex(clock)
    both = real_w.notna() & rebuilt_w.notna()
    a, b = chill.summarize(real_w.where(both)), chill.summarize(rebuilt_w.where(both))
    row = {"station": station_id, "winter": seasons.season_label(year), "hours_compared": int(both.sum()),
           "hours_left_out": int((~both).sum()),
           "hourly_typical_diff_F": float((rebuilt_w - real_w)[both].abs().mean())}
    for key, _, _ in MEASURES:
        row[f"real_{key}"], row[f"rebuilt_{key}"] = a[key], b[key]
        row[f"diff_{key}"] = b[key] - a[key]
    return row


def stats(rows: list[dict], key: str) -> dict:
    """Typical (mean absolute), worst (largest absolute, with its sign) and mean signed difference."""
    d = [r[f"diff_{key}"] for r in rows]
    worst = max(d, key=abs)
    return {"typical": sum(abs(x) for x in d) / len(d), "worst": worst, "mean": sum(d) / len(d)}


def summary_lines(rows: list[dict]) -> list[str]:
    """Markdown table of typical and worst difference per station and overall."""
    lines = ["| Stations | Winters | " + " | ".join(f"{n}: typical / worst / average" for _, n, _ in MEASURES) + " |",
             "|---|---|" + "---|" * len(MEASURES)]
    groups = [(NAMES[s], [r for r in rows if r["station"] == s]) for s in HOLDOUTS] + [("Both", rows)]
    for label, rs in groups:
        if not rs:
            continue
        cells = []
        for key, _, nd in MEASURES:
            m = stats(rs, key)
            cells.append(f"{m['typical']:.{nd}f} / {m['worst']:+.{nd}f} / {m['mean']:+.{nd}f}")
        lines.append(f"| {label} | {len(rs)} | " + " | ".join(cells) + " |")
    return lines


def winter_lines(rows: list[dict]) -> list[str]:
    """Markdown table, one row per station and winter."""
    lines = ["| Station | Winter | Hours compared | Hourly typical diff (°F) | Chill portions real → rebuilt (diff) "
             "| Chill hours real → rebuilt (diff) | Utah units real → rebuilt (diff) |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        cells = [f"{r['real_' + k]:.{nd}f} → {r['rebuilt_' + k]:.{nd}f} ({r['diff_' + k]:+.{nd}f})"
                 for k, _, nd in MEASURES]
        lines.append(f"| {r['station']} | {r['winter']} | {r['hours_compared']:,} | "
                     f"{r['hourly_typical_diff_F']:.1f} | " + " | ".join(cells) + " |")
    return lines


def lean_lines(rows: list[dict]) -> list[str]:
    """One line per measure: in how many winters the daily-only result was higher than the real one."""
    out = []
    for key, name, nd in MEASURES:
        d = [r[f"diff_{key}"] for r in rows]
        out.append(f"- {name.capitalize()}: daily-only higher in {sum(x > 0 for x in d)} of {len(d)} winters "
                   f"(range {min(d):+.{nd}f} to {max(d):+.{nd}f}).")
    return out


def pitch_sentence(rows: list[dict]) -> str:
    """The one line for the pitch, with the real numbers."""
    cp = stats(rows, "chill_portions")
    n_st = len({r["station"] for r in rows})
    return (f"Rebuilding hourly temperatures from just the daily high and low, our chill portions were usually "
            f"within {cp['typical']:.1f} of the real hourly result, and at most {abs(cp['worst']):.1f} off "
            f"({len(rows)} winters, {n_st} stations).")


def write_md(rows: list[dict], skipped: list[str]) -> None:
    """pitch/daily_only.md: summary, pitch sentence, per-winter table, method notes."""
    text = [
        "# Daily-only check: chill from daily highs and lows vs real hourly data",
        "",
        "**PRELIMINARY.** Generated by `scripts/daily_only_check.py` from saved CIMIS data (`data/cache/`).",
        "",
        "Julia Stover's ask: hourly temperatures rebuilt from daily data. For each winter we took a station's real",
        "hourly temperatures, kept only each day's low and high, rebuilt the hours with our port of chillR's",
        "`make_hourly_temps` (`backend/app/hourly_from_daily.py`), and counted chill Sept 1 to Feb 28 on both.",
        "Difference = rebuilt minus real (positive: the daily-only method counts more chill).",
        "",
        "## Pitch line",
        "",
        f"> {pitch_sentence(rows)}",
        "",
        "## Summary",
        "",
        *summary_lines(rows),
        "",
        "Typical = average size of the difference; worst = largest single winter (with its sign);",
        "average = signed mean (shows whether the method leans high or low).",
        "",
        *lean_lines(rows),
        "",
        "## Every winter",
        "",
        *winter_lines(rows),
        "",
        "## How it was done",
        "",
        "- A day's low and high come only from days with all 24 hours (CIMIS hour-ending labels, after the",
        "  app's usual fill of gaps up to 3 hours). Other days are missing, and so are their rebuilt hours.",
        "- Both sides are counted over the same hours: an hour missing on either side is left out of both.",
        "- Rebuilt hours are chillR's clock hours in solar time; CIMIS hours are averages labeled by hour ending.",
        "  That half-hour offset is part of the measured difference, not corrected for.",
        "- Latitude from the CIMIS station list (`data/cache/stations.parquet`).",
    ]
    if skipped:
        text += ["", "Not saved, so not compared: " + ", ".join(skipped) + "."]
    OUT_MD.write_text("\n".join(text) + "\n")


def main() -> None:
    """Compare every hold-out winter, print the summary, write pitch/daily_only.md."""
    stations = data.get_stations().set_index("station_id")
    rows, skipped = [], []
    for sid, years in HOLDOUTS.items():
        for year in years:
            row = compare_winter(sid, year, float(stations.loc[sid, "lat"]))
            if row is None:
                skipped.append(f"{sid} {seasons.season_label(year)}")
            else:
                rows.append(row)
    write_md(rows, skipped)
    print("\n".join(summary_lines(rows)))
    print(pitch_sentence(rows))
    print(f"Wrote {OUT_MD.relative_to(REPO)}")


if __name__ == "__main__":
    main()
