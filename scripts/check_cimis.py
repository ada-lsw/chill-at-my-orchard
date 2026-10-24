"""Check that real CIMIS data works, without ever printing the key.

Run from the repo root, in a Codespace or with a .env file:

    python scripts/check_cimis.py

It checks, in order:
  1. the key is set (prints only whether it exists)
  2. the station list loads, and Durham (12) shows as inactive
  3. the nearest active stations to each demo orchard
  4. one day of hourly temperature from Davis (6) parses into our data contract
If a step fails, it says which one and stops. Paste that message (never the key) to the team.
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ["DATA_SOURCE"] = "cimis"

from app import config, data, interp  # noqa: E402


def step(n, text):
    print(f"\n[{n}] {text}")


def main():
    step(1, "CIMIS key")
    if not config.CIMIS_APP_KEY:
        sys.exit("    FAIL: CIMIS_APP_KEY is not set. Add it as a Codespaces secret or in .env.")
    print("    ok: key is set")

    step(2, "Station list")
    try:
        st = data.get_stations()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"    FAIL: could not load the station list: {e}")
    print(f"    ok: {len(st)} stations, {int(st['active'].sum())} active")
    durham = st[st["station_id"] == "12"]
    if not durham.empty:
        print(f"    Durham (12): active={bool(durham['active'].iloc[0])} (expected False)")

    step(3, "Nearest active stations to each demo orchard")
    active = st[st["active"]]
    for key, d in config.DEMO_ORCHARDS.items():
        near = interp.nearest(active, d["lat"], d["lon"], config.NEIGHBORS, exclude=[d["holdout_station"]])
        print(f"    {key}: " + ", ".join(f"{r.station_id} {r['name']} ({r.dist_km:.0f} km, {r.elev_m:.0f} m)"
                                       for _, r in near.iterrows()))

    step(4, "One day of hourly temperature from Davis (6)")
    day = date.today() - timedelta(days=2)
    try:
        df = data._cimis_hourly("6", day, day)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"    FAIL: hourly request did not work: {e}")
    if df.empty or df["temp_F"].isna().all():
        sys.exit("    FAIL: request worked but no temperatures parsed. The field names in "
                 "data._cimis_hourly may not match CIMIS's response; tell the backend owner.")
    print(f"    ok: {len(df)} hours, {df['temp_F'].min():.1f} to {df['temp_F'].max():.1f} °F on {day}")
    print("\nAll checks passed. Next: python scripts/warm_cache.py")


if __name__ == "__main__":
    main()
