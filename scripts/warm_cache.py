"""Download and cache every station-season the demo needs, so the demo runs with Wi-Fi off.

Run from the repo root after scripts/check_cimis.py passes:

    python scripts/warm_cache.py

For each demo orchard it covers every winter the demo shows: the winter of its as_of date, the
config.HISTORY_SEASONS winters before it (the app's history), and on through today's winter.
For each of those seasons it does the same walk the app does
(interp.candidates, then interp.pick_neighbors): closest station first, keeping the first
NEIGHBORS that have data that season. It does this twice, around the pin (the demo) and around
the hold-out station (the proof), and caches the hold-out station itself. So the demo uses
exactly the stations cached here. Closed stations are tried too, because their old data helps
past winters; a season with no data is cached as empty, so it is never requested again.
One station and one season per request (CIMIS refuses large requests), pausing between requests.
Re-running skips anything already cached, so it is safe to stop and restart.
Files land in data/cache/ (git-ignored). Copy that folder to the demo laptops.
"""
import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DATA_SOURCE", "cimis")

from app import config, data, interp  # noqa: E402


def season_label(year: int) -> str:
    """A season the way the app writes it: 2024 -> "2024-25"."""
    return f"{year}-{str(year + 1)[-2:]}"


def seasons_to_cache(as_of: date, today: date) -> list[int]:
    """Every winter a demo shows: its own, the HISTORY_SEASONS before it, then on through today's."""
    return list(range(data.season_year(as_of) - config.HISTORY_SEASONS, data.season_year(today) + 1))


def coverage_once(pause: float):
    """data.season_coverage, asked at most once per station-season in this run.

    Sleeps `pause` seconds before any call that may reach CIMIS: a season that isn't cached,
    or the current season (data.season_hourly refreshes it once a day), so CIMIS isn't
    flooded. Remembering each answer means walks that share stations (demo and proof, and the
    hold-out itself) never read the same cache file twice.
    """
    seen: dict[tuple[str, int], float] = {}
    this_season = data.season_year(date.today())

    def coverage(station_id: str, year: int) -> float:
        """Share of `year`'s hours with a temperature at this station (downloads once if needed)."""
        if (station_id, year) not in seen:
            if year == this_season or not data.is_cached(station_id, year):
                time.sleep(pause)
            seen[(station_id, year)] = data.season_coverage(station_id, year)
        return seen[(station_id, year)]
    return coverage


def walk(stations, point: tuple, hold: str, coverage, year: int):
    """The app's neighbor walk around one (lat, lon, elev_m) point for one season."""
    lat, lon, elev = point
    cands = interp.candidates(stations, lat, lon, elev, exclude=[hold])
    return interp.pick_neighbors(cands, lambda sid: coverage(sid, year))


def describe(picks: dict) -> str:
    """'demo: 182, 146, ...  proof: ...', with "(only N)" when a walk found fewer than NEIGHBORS."""
    parts = []
    for label, p in picks.items():
        names = ", ".join(p["station_id"]) or "none"
        short = f" (only {len(p)})" if len(p) < config.NEIGHBORS else ""
        parts.append(f"{label}: {names}{short}")
    return "  ".join(parts)


def warm_demo(key: str, demo: dict, stations, coverage) -> int:
    """Cache one demo's hold-out and both walks (around the pin and the hold-out) for each season
    the demo shows (seasons_to_cache).

    Prints the stations chosen per season. Returns the number of seasons that failed.
    """
    years = seasons_to_cache(date.fromisoformat(demo["as_of"]), date.today())
    hold = demo["holdout_station"]
    elev, _ = interp.pin_elevation(stations, demo["lat"], demo["lon"])  # also saves the pin's elevation
    h = stations.set_index("station_id").loc[hold]
    points = {"demo": (demo["lat"], demo["lon"], elev), "proof": (h.lat, h.lon, h.elev_m)}
    print(f"\n{key}")
    failed = 0
    for y in years:
        try:
            hold_share = coverage(hold, y)
            picks = {label: walk(stations, p, hold, coverage, y) for label, p in points.items()}
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  {season_label(y)}: FAILED ({e}); re-run later")
            continue
        print(f"  {season_label(y)}  hold-out {hold}: {hold_share:.0%}  {describe(picks)}")
    return failed


def main():
    """Cache every station-season the demo orchards need, then say whether anything failed."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between requests")
    args = ap.parse_args()

    stations = data.get_stations()
    coverage = coverage_once(args.pause)
    failed = sum(warm_demo(key, d, stations, coverage) for key, d in config.DEMO_ORCHARDS.items())
    print("\nDone." if not failed else f"\n{failed} season(s) failed. Run again to retry just those.")


if __name__ == "__main__":
    main()
