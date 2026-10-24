"""Download and cache every station-season the demo needs, so the demo runs with Wi-Fi off.

Run from the repo root after scripts/check_cimis.py passes:

    python scripts/warm_cache.py              # 11 seasons (this one + 10 past) for both demos
    python scripts/warm_cache.py --seasons 5  # quicker first pass

For each demo orchard it caches the same station pool the app uses (interp.candidates): the
stations around the pin, the hold-out station, and the stations around the hold-out (for the
proof). Closed stations are included, because their old data helps estimate past winters.
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

    wanted = set()
    for key, d in config.DEMO_ORCHARDS.items():
        hold = d["holdout_station"]
        elev, _ = interp.pin_elevation(st, d["lat"], d["lon"])  # also saves the pin's elevation
        pool = interp.candidates(st, d["lat"], d["lon"], elev, exclude=[hold])
        h = st.set_index("station_id").loc[hold]
        proof_pool = interp.candidates(st, h.lat, h.lon, h.elev_m, exclude=[hold])
        print(f"{key}: pin pool " + ", ".join(
            f"{r.station_id} {r['name']} ({r.dist_km:.0f} km{'' if r.active else ', closed'})"
            for _, r in pool.iterrows()))
        wanted.update(pool["station_id"])
        wanted.update(proof_pool["station_id"])
        wanted.add(hold)

    jobs = [(s, y) for s in sorted(wanted) for y in years]
    print(f"{len(wanted)} stations x {len(years)} seasons = {len(jobs)} station-seasons")
    for i, (sid, y) in enumerate(jobs, 1):
        cache = config.CACHE_DIR / f"hourly_{config.DATA_SOURCE}_{sid}_{y}.parquet"
        if cache.exists() and y != this_season:
            print(f"  [{i}/{len(jobs)}] {sid} {y}-{y + 1}: cached")
            continue
        try:
            df = data.season_hourly(sid, y)
            missing = int(df["temp_F"].isna().sum()) if not df.empty else 0
            print(f"  [{i}/{len(jobs)}] {sid} {y}-{y + 1}: {len(df)} hours, {missing} missing")
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{len(jobs)}] {sid} {y}-{y + 1}: FAILED ({e}); re-run later")
        time.sleep(args.pause)
    print("Done. data/cache/ now holds everything the demo needs.")


if __name__ == "__main__":
    main()
