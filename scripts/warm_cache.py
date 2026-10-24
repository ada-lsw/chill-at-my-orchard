"""Download and cache every station-season the demo needs, so the demo runs with Wi-Fi off.

Run from the repo root after scripts/check_cimis.py passes:

    python scripts/warm_cache.py              # 11 seasons (this one + 10 past) for both demos
    python scripts/warm_cache.py --seasons 5  # quicker first pass

For each demo orchard and each season it does the same walk the app does
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, default=11, help="this season plus this many minus one past")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between requests")
    args = ap.parse_args()

    st = data.get_stations()
    this_season = data.season_year(date.today())
    years = list(range(this_season - args.seasons + 1, this_season + 1))

    def coverage(sid, year):
        """data.season_coverage, pausing after any real download so CIMIS isn't flooded."""
        cached = (config.CACHE_DIR / f"hourly_{config.DATA_SOURCE}_{sid}_{year}.parquet").exists()
        share = data.season_coverage(sid, year)
        if not cached:
            time.sleep(args.pause)
        return share

    failed = 0
    for key, d in config.DEMO_ORCHARDS.items():
        hold = d["holdout_station"]
        elev, _ = interp.pin_elevation(st, d["lat"], d["lon"])  # also saves the pin's elevation
        h = st.set_index("station_id").loc[hold]
        points = {"demo": (d["lat"], d["lon"], elev), "proof": (h.lat, h.lon, h.elev_m)}
        print(f"\n{key}")
        for y in years:
            try:
                hold_share = coverage(hold, y)
                picks = {}
                for label, (lat, lon, e) in points.items():
                    cands = interp.candidates(st, lat, lon, e, exclude=[hold])
                    picks[label] = interp.pick_neighbors(cands, lambda sid: coverage(sid, y))
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"  {y}-{str(y + 1)[-2:]}: FAILED ({e}); re-run later")
                continue
            line = "  ".join(f"{label}: " + (", ".join(p["station_id"]) or "none")
                             + (f" (only {len(p)})" if len(p) < config.NEIGHBORS else "")
                             for label, p in picks.items())
            print(f"  {y}-{str(y + 1)[-2:]}  hold-out {hold}: {hold_share:.0%}  {line}")
    print("\nDone." if not failed else f"\n{failed} season(s) failed. Run again to retry just those.")


if __name__ == "__main__":
    main()
