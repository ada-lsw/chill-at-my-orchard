"""The proof table: how close is the estimate when we hide a real station? Tries 8 settings, picks one.

Run from the repo root, with saved data only (no downloads; a station-season that isn't saved counts as
missing and marks that setting "incomplete"):

    python scripts/validation_table.py

For each setting it hides Durham (12) for winters 2016-17 to 2024-25 and Shafter (5) for 2016-17 to
2025-26, estimates the hidden station from its neighbors (the same steps as /validate), and compares
chill counted Sept 1 to Feb 28. Writes pitch/validation.csv (one row per setting, station and winter)
and pitch/validation.md (summary, the recommended setting, lines for the pitch).

The 8 settings are every combination of: elevation adjustment on (the standard 6.5 °C/km lapse) or off;
5 or 3 neighbors; distance and elevation caps on (config values) or off. No other values have a source.
"""
from __future__ import annotations

import csv
import itertools
import math
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
os.environ.setdefault("DATA_SOURCE", "cimis")

from app import chill, config, data, interp, main, seasons  # noqa: E402

# 6.5 °C/km standard atmospheric lapse rate in °F per meter: the "on" value, and what config shipped
# before this table picked a setting. Fixed here so shipping a winner never changes the grid.
STANDARD_LAPSE_F_PER_M = 0.0117
CAPS_ON = (config.MAX_NEIGHBOR_KM, config.MAX_ELEV_DIFF_M)   # the caps "on": config values (100 km, 300 m)
HOLDOUTS = {"12": range(2016, 2025), "5": range(2016, 2026)}      # season start years
DEMO_NAMES = {"12": "Durham (12)", "5": "Shafter (5), the Kern pin"}
OUT_CSV, OUT_MD = REPO / "pitch" / "validation.csv", REPO / "pitch" / "validation.md"


@dataclass(frozen=True)
class Setting:
    """One combination of the three choices the table tries."""
    lapse_f_per_m: float
    neighbors: int
    max_km: float
    max_elev_m: float

    @property
    def name(self) -> str:
        """Plain name, e.g. "elevation on, 5 neighbors, caps on"."""
        elev = "on" if self.lapse_f_per_m else "off"
        caps = "on" if math.isfinite(self.max_km) else "off"
        return f"elevation {elev}, {self.neighbors} neighbors, caps {caps}"


PREVIOUS = Setting(STANDARD_LAPSE_F_PER_M, 5, *CAPS_ON)     # the setting before this table


def settings_grid() -> list[Setting]:
    """The 8 settings: elevation adjustment on/off × 5 or 3 neighbors × caps on/off (inf = no cap)."""
    return [Setting(lapse, k, *caps) for lapse, k, caps in itertools.product(
        (STANDARD_LAPSE_F_PER_M, 0.0), (5, 3), (CAPS_ON, (math.inf, math.inf)))]


@contextmanager
def applied(setting: Setting):
    """Use this setting's values in config while the block runs (in memory only), then put the old ones back."""
    names = ("LAPSE_F_PER_M", "NEIGHBORS", "MAX_NEIGHBOR_KM", "MAX_ELEV_DIFF_M")
    saved = [getattr(config, n) for n in names]
    try:
        for n, v in zip(names, (setting.lapse_f_per_m, setting.neighbors, setting.max_km, setting.max_elev_m)):
            setattr(config, n, v)
        yield
    finally:
        for n, v in zip(names, saved):
            setattr(config, n, v)


def holdout_row(stations, setting: Setting, station_id: str, year: int, uncached: set) -> dict | None:
    """Hide one station for one winter and estimate it from its neighbors, from saved data only.

    The same steps as main.validate, except that a station-season that isn't saved counts as no data
    and is added to `uncached` (main.validate would download it). None if the hidden station isn't saved.
    """
    if not data.is_cached(station_id, year):
        uncached.add((station_id, year))
        return None
    start, end, _ = seasons.chill_window(date(year + 1, 2, 28))
    target = stations.set_index("station_id").loc[station_id]

    def coverage(sid: str) -> float:
        """Share of the winter's hours a saved station has; 0 (and noted) if it isn't saved."""
        if not data.is_cached(sid, year):
            uncached.add((sid, year))
            return 0.0
        return data.season_coverage(sid, year)

    with applied(setting):
        cands = interp.candidates(stations, target.lat, target.lon, target.elev_m, exclude=[station_id])
        neigh = interp.pick_neighbors(cands, coverage)
        hourly = main.load_hourly(list(neigh["station_id"]) + [station_id], start, end)
        r = interp.leave_one_out(stations, hourly, station_id, chill.summarize, neighbors=neigh)
    return {"setting": setting.name, "station": station_id, "winter": f"{year}-{str(year + 1)[-2:]}",
            "neighbors": " ".join(neigh["station_id"]), "error_cp": r["error"]["chill_portions"],
            "error_chill_hours": r["error"]["chill_hours"], "error_utah": r["error"]["utah_units"],
            "hours_compared": r["hours_compared"], "true_cp": round(r["actual"]["chill_portions"], 1)}


def summarize(errors: list[float]) -> dict:
    """Lean (mean error), typical miss (mean absolute error), worst miss (sign kept), winters high and low."""
    return {"n": len(errors), "lean": sum(errors) / len(errors),
            "typical_miss": sum(abs(e) for e in errors) / len(errors),
            "worst": max(errors, key=abs), "high": sum(e > 0 for e in errors), "low": sum(e < 0 for e in errors)}


def within(errors: list[float], limit: float) -> int:
    """How many winters the estimate missed by no more than `limit` chill portions."""
    return sum(abs(e) <= limit for e in errors)


def changes_from_previous(s: Setting) -> int:
    """How many of the three choices differ from the setting before this table."""
    return ((s.lapse_f_per_m != PREVIOUS.lapse_f_per_m) + (s.neighbors != PREVIOUS.neighbors)
            + (s.max_km != PREVIOUS.max_km))


def pick_winner(scores: dict[Setting, dict]) -> tuple[Setting, str]:
    """Ada's rule (Amendment D), exactly. scores: {setting: {"typical_miss", "complete"}} over all 19 winters.

    1. Only complete settings (no uncached station skipped). 2. Lowest typical miss; an exact tie goes to
    the setting with fewer changes. 3. If that ties the previous setting at 1 decimal, keep the previous.
    4. Caps can be turned off (no cap), but this PR may change only the lapse rate and neighbor count in
    config: a winner with caps off is reported for Ada, and the best caps-on setting ships.
    """
    ranked = sorted((s for s, v in scores.items() if v["complete"]),
                    key=lambda s: (scores[s]["typical_miss"], changes_from_previous(s)))
    best = ranked[0]
    if PREVIOUS in scores and round(scores[best]["typical_miss"], 1) == round(scores[PREVIOUS]["typical_miss"], 1):
        return PREVIOUS, ""
    if math.isfinite(best.max_km):
        return best, ""
    shipped = next(s for s in ranked if math.isfinite(s.max_km))
    return shipped, (f"DECISION FOR ADA: '{best.name}' had the lowest typical miss "
                     f"({scores[best]['typical_miss']:.2f}), but turning the caps off isn't a change this PR "
                     f"may make; shipping the best setting with caps on, '{shipped.name}'.")


def run_grid(stations) -> tuple[list[dict], dict[Setting, set]]:
    """Every row for every setting, and the uncached station-seasons each setting ran into."""
    rows, uncached = [], {}
    for setting in settings_grid():
        uncached[setting] = set()
        for sid, years in HOLDOUTS.items():
            for y in years:
                row = holdout_row(stations, setting, sid, y, uncached[setting])
                if row:
                    rows.append(row)
    return rows, uncached


def check_real_data() -> None:
    """Stop unless this run uses real CIMIS data, so a synthetic run never overwrites the pitch numbers."""
    if config.DATA_SOURCE != "cimis":
        raise SystemExit(f"DATA_SOURCE is {config.DATA_SOURCE!r}; run with DATA_SOURCE=cimis (saved data only).")


def write_csv(rows: list[dict]) -> None:
    """pitch/validation.csv: one row per setting, station and winter."""
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def errors_of(rows: list[dict], setting: Setting, station: str | None = None) -> list[float]:
    """Chill-portion errors for one setting, for one hidden station or all of them."""
    return [r["error_cp"] for r in rows if r["setting"] == setting.name and station in (None, r["station"])]


# ---------------------------------------------------------------- pitch/validation.md

def fmt(x: float) -> str:
    """A signed error with one decimal, e.g. +4.8 or -8.8."""
    return f"{x:+.1f}"


def settings_table(rows, uncached, scores) -> list[str]:
    """One line per setting: complete or not, typical miss over all 19 winters, and each demo's summary."""
    out = ["| Setting | Complete | Typical miss, all 19 winters | Durham (12): lean / typical / worst / high-low "
           "| Shafter (5): lean / typical / worst / high-low |", "|---|---|---|---|---|"]
    for s in settings_grid():
        cells = []
        for sid in HOLDOUTS:
            m = summarize(errors_of(rows, s, sid))
            cells.append(f"{fmt(m['lean'])} / {m['typical_miss']:.1f} / {fmt(m['worst'])} / {m['high']}-{m['low']}")
        done = "yes" if scores[s]["complete"] else f"no ({len(uncached[s])} station-seasons not saved: " + \
            ", ".join(f"{a} in {b}-{str(b + 1)[-2:]}" for a, b in sorted(uncached[s])) + ")"
        out.append(f"| {s.name} | {done} | {scores[s]['typical_miss']:.2f} | {cells[0]} | {cells[1]} |")
    return out


def best_per_demo(rows, scores) -> list[str]:
    """Which complete setting has the lowest typical miss for each demo on its own."""
    out = []
    for sid, label in DEMO_NAMES.items():
        best = min((s for s in settings_grid() if scores[s]["complete"]),
                   key=lambda s: summarize(errors_of(rows, s, sid))["typical_miss"])
        out.append(f"- {label}: {best.name} ({summarize(errors_of(rows, best, sid))['typical_miss']:.2f}).")
    return out


def lean_with_and_without(rows, setting: Setting, station: str = "54") -> str:
    """Shafter's lean in winters with `station` among the neighbors and without it (a description only)."""
    mine = [r for r in rows if r["setting"] == setting.name and r["station"] == "5"]
    groups = {True: [r["error_cp"] for r in mine if station in r["neighbors"].split()],
              False: [r["error_cp"] for r in mine if station not in r["neighbors"].split()]}
    parts = [f"{'with' if k else 'without'} {station}: {fmt(sum(v) / len(v))} over {len(v)} winters"
             for k, v in groups.items() if v]
    if not groups[True]:
        parts.append(f"station {station} is never one of the neighbors in this setting")
    return f"- {setting.name}: " + "; ".join(parts) + "."


def how_sure_lines(rows, setting: Setting) -> list[str]:
    """Draft plain-language lines for Jina, each with the count of winters it is true for."""
    out = []
    for sid, label in DEMO_NAMES.items():
        errs = errors_of(rows, setting, sid)
        m = summarize(errs)
        x = max(1, round(m["typical_miss"]))
        out.append(f"- {label}: \"off by about {x} chill portions in a typical winter; within {x} in "
                   f"{within(errs, x)} of {len(errs)} winters\" (typical miss {m['typical_miss']:.1f}; within {x + 1} in "
                   f"{within(errs, x + 1)}, within {x + 2} in {within(errs, x + 2)}).")
    return out


def closed_near_kern(stations) -> tuple[int, int, int]:
    """Of the 10 CIMIS stations nearest the Kern pin (Shafter itself left out): how many are listed as closed,
    and how many of those have no saved data in any winter from 2016-17 on."""
    kern = config.DEMO_ORCHARDS["kern"]
    near = interp.nearest(stations, kern["lat"], kern["lon"], 10, exclude=[kern["holdout_station"]])
    closed = near[~near["active"]]
    silent = sum(all(not data.is_cached(sid, y) or data.season_coverage(sid, y) == 0 for y in range(2016, 2026))
                 for sid in closed["station_id"])
    return len(near), len(closed), silent


def pitch_numbers(rows, winner: Setting, stations) -> list[str]:
    """Amendment G: one line per number, each with its source. Numbers from later tasks are marked pending."""
    d, k_before, k_after = (summarize(errors_of(rows, winner, "12")), summarize(errors_of(rows, PREVIOUS, "5")),
                            summarize(errors_of(rows, winner, "5")))
    n, closed, silent = closed_near_kern(stations)
    src = "source: pitch/validation.csv, scripts/validation_table.py"
    return [
        f"- Durham (station 12 hidden, {d['n']} winters): typical miss {d['typical_miss']:.1f} chill portions, "
        f"worst {fmt(d['worst'])}. ({src}, shipped setting)",
        f"- Kern (Shafter hidden, {k_after['n']} winters): lean {fmt(k_before['lean'])} before, "
        f"{fmt(k_after['lean'])} with the shipped setting; too high in {k_after['high']} of {k_after['n']} winters. ({src})",
        f"- Shipped setting: {winner.name}. ({src}, Ada's rule, Amendment D)",
        f"- {closed} of the {n} nearest CIMIS stations to the Kern pin are listed as closed; {silent} of them have no "
        f"saved data in any winter since 2016-17. (source: CIMIS station list, data/cache/stations.parquet `active`, "
        f"and the saved CIMIS data; computed by scripts/validation_table.py)",
        "- Kern card for Feb 1, 2026 with Shafter's real data: pending (kern-real-station PR).",
        "- Trend sentence for both demos: pending (history-trend PR).",
        "- \"Our chill matches FNRIC within X\": pending (golden tests, B2).",
    ]


def write_md(path: Path, rows, uncached, scores, winner: Setting, note: str, stations) -> None:
    """pitch/validation.md: the settings, the recommendation, notes, and the numbers for the pitch."""
    w = scores[winner]["typical_miss"]
    same_k_caps = [s for s in settings_grid() if s.neighbors == winner.neighbors and s.max_km == winner.max_km
                   and s.lapse_f_per_m != winner.lapse_f_per_m]
    margin = (f"At {winner.neighbors} neighbors with the same caps, elevation {'off' if winner.lapse_f_per_m else 'on'} "
              f"gives {scores[same_k_caps[0]]['typical_miss']:.2f}, so the elevation adjustment makes no measurable "
              f"difference here; most of the change comes from the number of neighbors." if same_k_caps else "")
    lines = [
        "# Validation: how close is the estimate where a station is hidden?", "",
        "Made by `scripts/validation_table.py` from saved CIMIS hourly data (no downloads). Each row hides one "
        "station for one winter and estimates it from its neighbors, as `/validate` does. Chill is counted Sept 1 to "
        "Feb 28. Hidden: Durham (12) for winters 2016-17 to 2024-25 (9) and Shafter (5) for 2016-17 to 2025-26 (10). "
        "Errors are estimate minus the station's own reading, in chill portions. Every row: `pitch/validation.csv`.", "",
        "Lean = average error (positive: the estimate runs high). Typical miss = average size of the error. "
        "Worst = the largest miss. \"Caps off\" removes the 100 km and 300 m limits, but the walk still looks at "
        "the 30 closest stations only (`NEIGHBOR_CANDIDATES`).", "",
        "## The 8 settings", "", *settings_table(rows, uncached, scores), "",
        "## Recommended setting", "",
        f"**{winner.name}**: typical miss {w:.2f} chill portions over all 19 winters, against "
        f"{scores[PREVIOUS]['typical_miss']:.2f} for the setting before ({PREVIOUS.name}).", "",
        "Rule (Ada, Amendment D): complete settings only; lowest typical miss over all 19 winters; a tie with the "
        "previous setting at 1 decimal keeps the previous one; an exact tie goes to the setting with fewer changes.",
        *([note] if note else []), "", "Best for each demo on its own:", *best_per_demo(rows, scores), "",
        "Picking the best of 8 settings on the same 19 winters slightly flatters the winner: its miss on new winters "
        "will likely be a little larger. " + margin, "",
        "## Kern: winters with Blackwells Corner (54) as a neighbor", "",
        "Described only, not a conclusion (few winters each):",
        lean_with_and_without(rows, PREVIOUS), lean_with_and_without(rows, winner), "",
        "## Does Kern's high lean shrink?", "",
        *[f"- {s.name}: lean {fmt(summarize(errors_of(rows, s, '5'))['lean'])}, too high in "
          f"{summarize(errors_of(rows, s, '5'))['high']} of 10 winters" for s in settings_grid()], "",
        "## How sure: draft lines for Jina", "",
        "From the shipped setting. \"Usually within X\" from the typical miss alone would overstate Kern: "
        "only about half its winters fall inside it. So each line says how many winters it is true for.",
        *how_sure_lines(rows, winner), "",
        "## Notes", "",
        "- With 3 neighbors, `scripts/warm_cache.py` saves 3 stations per winter. On a fresh machine, the 5-neighbor "
        "rows need `NEIGHBORS=5 python scripts/warm_cache.py` first, or they show as incomplete.",
        "- Synthetic data (`data.synthetic_temp`) also uses `LAPSE_F_PER_M`, so with 0 it has no elevation effect.", "",
        "## Numbers for the pitch", "", *pitch_numbers(rows, winner, stations), "",
    ]
    path.write_text("\n".join(lines))


def run() -> None:
    """Run the grid from saved data, print the summary, write pitch/validation.csv and .md."""
    check_real_data()
    stations = data.get_stations()
    rows, uncached = run_grid(stations)
    scores = {s: {"typical_miss": summarize(errors_of(rows, s))["typical_miss"], "complete": not uncached[s]}
              for s in settings_grid()}
    winner, note = pick_winner(scores)
    write_csv(rows)
    write_md(OUT_MD, rows, uncached, scores, winner, note, stations)
    for s in settings_grid():
        flag = "" if scores[s]["complete"] else f"  INCOMPLETE ({len(uncached[s])} not saved)"
        print(f"{s.name:38} typical miss {scores[s]['typical_miss']:.2f}{flag}")
    print(f"\nShip: {winner.name}. {note}")


if __name__ == "__main__":
    run()
