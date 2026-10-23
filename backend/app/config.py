"""Shared settings. Change values here (or via environment variables), not in code."""
import os
from pathlib import Path

# Where cached station data lives. Mounted as a Docker volume so it survives rebuilds.
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# "cimis" = real data from the CIMIS API (needs CIMIS_APP_KEY).
# "synthetic" = generated fake data so the frontend can be built before real data lands.
DATA_SOURCE = os.getenv("DATA_SOURCE", "synthetic")
CIMIS_APP_KEY = os.getenv("CIMIS_APP_KEY", "")

TIMEZONE = "America/Los_Angeles"

# Chill season: counting starts Nov 1 (month, day). Say this in the UI and the pitch.
CHILL_START = (11, 1)
# Chill hours window, °F
CHILL_HOURS_LOW_F = 32.0
CHILL_HOURS_HIGH_F = 45.0

# GDD: season start and base temperature by crop, °F.
# OPEN QUESTION: confirm crop base temperatures with FNRIC before the demo.
GDD_START = (3, 1)
GDD_BASE_F = {"almond": 50.0, "walnut": 50.0, "pistachio": 45.0, "prune": 41.0}

# Interpolation
NEIGHBORS = int(os.getenv("NEIGHBORS", 5))      # stations used for each estimate
IDW_POWER = float(os.getenv("IDW_POWER", 2.0))
# Temperature change per meter of elevation, °F/m (standard lapse 6.5 °C/km ≈ 0.0117 °F/m).
# Winter valley inversions can make this wrong; validation decides the value we ship.
LAPSE_F_PER_M = float(os.getenv("LAPSE_F_PER_M", 0.0117))

# Gaps up to this many hours are filled by linear interpolation; longer gaps stay missing.
MAX_FILL_HOURS = 3

# Preset demo orchards. Coordinates are placeholders until the team picks real spots.
DEMO_ORCHARDS = {
    "durham": {
        "label": "Durham, Butte County (station removed)",
        "lat": 39.61, "lon": -121.82,
        "holdout_station": "12",  # Durham CIMIS station, stopped reporting July 2025
    },
    "foothill": {
        "label": "Foothill orchard (elevation)",
        "lat": 38.90, "lon": -121.05,
        "holdout_station": None,  # TODO: pick a foothill CIMIS station from the station list
    },
}
