"""Shared settings. Change values here (or via environment variables), not in code."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load the repo-root .env (CIMIS key, data source). Real environment variables win.
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env", override=False)

# Where cached station data lives (repo-root data/ folder by default).
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# "cimis" = real data from the CIMIS API (needs CIMIS_APP_KEY).
# "synthetic" = generated fake data so the frontend can be built before real data lands.
DATA_SOURCE = os.getenv("DATA_SOURCE", "synthetic")
# New CIMIS "Web API App Key" from your cimis.water.ca.gov account page (32 characters).
# Sent as a header, never in a URL. Stray quotes or spaces from copy-paste are stripped.
CIMIS_APP_KEY = os.getenv("CIMIS_APP_KEY", "").strip().strip('"').strip("'")

TIMEZONE = "America/Los_Angeles"

# Chill season start (month, day). FNRIC starts its Dynamic Model season on Sept 1
# (fruitsandnuts.ucdavis.edu/about-chilling-hours-units-and-portions), and the chill-portion
# targets below are counted from Sept 1 too, so every chill measure counts from Sept 1.
# Growers traditionally start counting chill hours in November; set CHILL_START_MONTH=11 to
# show that view. Always tell the grower the start date on screen.
CHILL_START = (int(os.getenv("CHILL_START_MONTH", 9)), 1)

# Default "hours in a range" the grower sees; they can change it in the app.
CUSTOM_RANGE_F = (32.0, 45.0)

# GDD counts from bloom (FNRIC's almond hull split model counts from full bloom date).
# ASSUMPTION: Feb 20 as a typical almond bloom date. Ask FNRIC; let growers enter their own.
GDD_START = (2, 20)
# Single-sine thresholds in °C (lower, upper). FNRIC: 5°C (41°F) and 35°C (95°F).
GDD_THRESHOLDS_C = {"almond": (5.0, 35.0), "walnut": (5.0, 35.0),
                    "pistachio": (5.0, 35.0), "prune": (5.0, 35.0)}  # TODO: confirm non-almond crops

# Interpolation. NEIGHBORS and LAPSE_F_PER_M: chosen by scripts/validation_table.py over 19 hold-out
# winters; see pitch/validation.md.
NEIGHBORS = int(os.getenv("NEIGHBORS", 3))      # stations used for each estimate (5 was tried too)
IDW_POWER = float(os.getenv("IDW_POWER", 2.0))
# Temperature change per meter of elevation, °F/m. 0 = no elevation adjustment. The standard lapse
# (6.5 °C/km ≈ 0.0117 °F/m) was tried and made no measurable difference over those winters (winter
# valley inversions can make it wrong), so it is off.
LAPSE_F_PER_M = float(os.getenv("LAPSE_F_PER_M", 0.0))

# Which stations may be neighbors (interp.candidates). For each season, the app walks this list
# closest first and keeps the first NEIGHBORS stations that have data that season;
# scripts/warm_cache.py does the same walk, so the demo uses exactly the stations it cached.
# Closed stations are included: their old data helps estimate past winters. Many stations near
# the demo orchards are listed as closed (8 of the 10 nearest to the Kern pin at Shafter, 7 of
# them with no data since 2016), so the list is long.
NEIGHBOR_CANDIDATES = int(os.getenv("NEIGHBOR_CANDIDATES", 30))  # most stations walked
# Starting values, not from a source. scripts/validation_table.py tried the caps on and off and kept
# them on (pitch/validation.md).
MAX_NEIGHBOR_KM = float(os.getenv("MAX_NEIGHBOR_KM", 100))
MAX_ELEV_DIFF_M = float(os.getenv("MAX_ELEV_DIFF_M", 300))   # about 1,000 ft above or below the pin
# A station counts for a season only if it has a temperature for at least this share of the
# season's hours; otherwise the next closest station takes its place. Also a starting value.
MIN_NEIGHBOR_COVERAGE = float(os.getenv("MIN_NEIGHBOR_COVERAGE", 0.5))

# Gaps up to this many hours are filled by linear interpolation; longer gaps stay missing.
MAX_FILL_HOURS = 3

# ---------------------------------------------------------------- crops and decisions
# Chill targets in chill portions (Dynamic Model, counted from Sept 1). Ranges come from the
# team plan's Target crops table (UCCE chill portion requirements). "target" is the single
# number the tool compares against; each one is a DRAFT to confirm with FNRIC (Julia Stover).
VARIETIES = {
    "Chandler walnut":   {"crop": "walnut",    "range_cp": (45, 50), "target_cp": 50,
                          "note": "top of the UCCE range, to stay conservative"},
    "Hartley walnut":    {"crop": "walnut",    "range_cp": (54, 54), "target_cp": 54, "note": "UCCE"},
    "Kerman pistachio":  {"crop": "pistachio", "range_cp": (54, 58), "target_cp": 57,
                          "note": "yields stayed average until chill fell below about 57"},
    "Peters pistachio":  {"crop": "pistachio", "range_cp": (58, 65), "target_cp": 62, "note": "UCCE, midpoint"},
    "Nonpareil almond":  {"crop": "almond",    "range_cp": (22, 23), "target_cp": 23, "note": "UCCE"},
    "Improved French prune": {"crop": "prune", "range_cp": (55, 60), "target_cp": 58, "note": "UCCE, midpoint"},
}
# Crop menu order from the team plan.
CROP_ORDER = ["walnut", "pistachio", "almond", "prune"]

# Verdict band: where chill so far sits among past seasons on the same date (percentiles).
VERDICT_LOW_PCT = 20     # below this: "low"
VERDICT_HIGH_PCT = 80    # above this: "high"; between: "normal"

# Past winters the app compares against (/estimate history, /decision scenarios): the verdict
# band above and the status shares below are over these. scripts/warm_cache.py caches exactly
# these winters for the demo orchards, so the demo shows the same history with Wi-Fi off as online.
HISTORY_SEASONS = 10

# Decision support. Status counts how many past seasons, added to chill so far, reach the
# variety's target by TARGET_DATE. Draft rules from the team plan; confirm with Julia.
TARGET_DATE = (3, 2)          # month, day. West Coast Nut: pistachio target 62-65 CP by about Mar 2
STATUS_ON_TRACK_SHARE = 0.8   # 8+ of 10 past seasons reach the target
STATUS_WATCH_SHARE = 0.4      # 4-7 of 10; below this is "at risk"
# Chill portion level where rest-breaking treatments start to work, by crop. Only crops with a
# sourced number get a decision window; others show the shortfall and "talk to your PCA".
DECISION_MILESTONE_CP = {"pistachio": 55}   # West Coast Nut: best at ~55-58 CP, no effect at <=50

# What low chill does to trees (FNRIC, about chilling hours, units and portions).
LOW_CHILL_SYMPTOMS = ["delayed and extended bloom", "delayed leaf-out",
                      "reduced fruit set", "reduced fruit quality"]

# Option types to raise with a licensed Pest Control Adviser. Never rates, mixes or timing:
# in California recommending agricultural pesticide use (including growth regulators) needs a
# PCA license (CDPR). Every list ends by pointing to the PCA.
INTERVENTION_OPTIONS = {
    "pistachio": [
        {"type": "Rest-breaking agents",
         "detail": "Hydrogen cyanamide is the most common on pistachio and can injure trees.",
         "source": "https://www.semios.com/resources/blog/california-pistachio-chill-update-frequently-asked-questions/"},
        {"type": "Other agents",
         "detail": "Hormone analogs and nitrogen-based mixes.",
         "source": "https://wcngg.com/?p=15944"},
        {"type": "Orchard practices",
         "detail": "Cover crops advanced bloom about five to six days in one trial.",
         "source": "https://wcngg.com/?p=15944"},
    ],
}
PCA_HANDOFF = "Talk to your Pest Control Adviser (PCA) about whether any of these fit your orchard."

# ---------------------------------------------------------------- demo orchards
# One of each story: a removed station (walnut, north) and a pistachio orchard (south).
DEMO_ORCHARDS = {
    "durham": {
        "label": "Durham walnuts, Butte County (station removed)",
        "lat": 39.61, "lon": -121.82, "variety": "Chandler walnut",
        "holdout_station": "12",  # Durham CIMIS station, stopped reporting July 2025
        "as_of": "2026-02-01",    # replay the first winter with no Durham station
    },
    "kern": {
        "label": "Kern pistachios (far from a station)",
        # Pin on Shafter's own coordinates (CIMIS station 5, from the CIMIS station list) while
        # Shafter is hidden: the hold-out proof (/validate for station 5) then measures the
        # estimate's error at exactly the spot this demo shows.
        "lat": 35.532556, "lon": -119.28179, "variety": "Kerman pistachio",
        "holdout_station": "5",   # hide Shafter to prove the estimate where stations are sparse
        "as_of": "2026-02-01",
    },
}
