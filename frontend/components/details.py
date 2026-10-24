"""Details layer ("Show the numbers"): every measure, accuracy, sources.  Owner: Frontend B.

Every number has a one-line explanation in its tooltip (the "?" next to it). The explanations
are written in the backend (config.MEASURE_HELP, served by /glossary); this file only shows them.
"""
from datetime import date

import streamlit as st

from api import get

FEET_PER_METER = 3.28084   # growers think in feet (Drew, #14)


def help_for(key: str) -> str:
    """The plain one-line explanation of a measure, from the backend's /glossary."""
    return get("/glossary")["measures"][key]


def _day(iso: str) -> str:
    """'2025-09-01' -> 'Sep 1', the way growers write dates."""
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def _season_label(season: str) -> str:
    """The backend's '2024-09-01 to 2025-02-28' -> 'Sep 1, 2024 to Feb 28, 2025' (display only)."""
    start, end = (date.fromisoformat(part.strip()) for part in season.split(" to "))
    return f"{_day(str(start))}, {start.year} to {_day(str(end))}, {end.year}"


def show(place: dict, est: dict, dec: dict):
    """Draw the Details layer: the measures, the grower's range, options for a PCA, and the proof."""
    _measures(est)
    _custom_range(est["chill"]["custom_range"])
    _pca_options(dec)
    _proof(place.get("holdout_station"), est)


def _measures(est: dict):
    """Chill, heat and data-quality numbers, each with its explanation as a tooltip."""
    ch, g = est["chill"], est["gdd"]
    st.caption(f"Counting since {_day(ch['start'])}", help=help_for("chill_start"))
    lo, hi = g["thresholds_c"]
    warmth = f"{g['total_c_days']:.0f} °C-days" if g["started"] else "Not yet"
    _metric_rows([
        ("Chill portions", f"{ch['chill_portions']:.1f}", help_for("chill_portions")),
        ("Chill hours (32-45°F)", f"{ch['chill_hours']:.0f}", help_for("chill_hours")),
        ("Hours at or below 45°F", f"{ch['hours_lt_45']:.0f}", help_for("hours_lt_45")),
        ("Utah chill units", f"{ch['utah_units']:.0f}", help_for("utah_units")),
        (f"Warmth (GDD) since {_day(g['start'])}, {_c_to_f(lo):.0f}-{_c_to_f(hi):.0f}°F", warmth, help_for("gdd")),
        ("Hours missing", f"{ch['hours_missing']}", help_for("hours_missing")),
        ("Nearby stations used", f"{len(est['neighbors'])}", help_for("neighbors")),
        ("Orchard elevation", f"{est['location']['elev_m'] * FEET_PER_METER:,.0f} ft", help_for("elevation")),
    ])


def _c_to_f(c: float) -> float:
    """Convert a temperature from °C to °F, for display only."""
    return c * 9 / 5 + 32


def _metric_rows(items: list[tuple], per_row: int = 2):
    """Show (label, value, tooltip) metrics two per row, so labels stay readable on a phone."""
    for i in range(0, len(items), per_row):
        for col, (label, value, tip) in zip(st.columns(per_row), items[i:i + per_row]):
            col.metric(label, value, help=tip)


def _custom_range(r: dict):
    """Hours below, inside and above the grower's own temperature range."""
    lo, hi = r["low_f"], r["high_f"]
    st.markdown(f"**Your temperature range: {lo:g}°F to {hi:g}°F**")
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Hours at or below {lo:g}°F", f"{r['hours_below']:.0f}", help=help_for("custom_below"))
    c2.metric(f"Hours {lo:g}-{hi:g}°F", f"{r['hours_between']:.0f}", help=help_for("custom_between"))
    c3.metric(f"Hours above {hi:g}°F", f"{r['hours_above']:.0f}", help=help_for("custom_above"))


def _pca_options(dec: dict):
    """What low chill can do, option types to raise with a PCA (with sources), and the guardrail.

    Whenever options are listed, the backend's ready-made "talk to your PCA" sentence
    (dec["pca_handoff"]) is shown right after them, word for word, so the list always
    ends by sending the grower to their Pest Control Adviser.
    """
    st.markdown("**What low chill can do:** " + ", ".join(dec["low_chill_symptoms"]) + ".")
    if dec["options"]:
        st.markdown("**Options to raise with your PCA:**")
        for o in dec["options"]:
            st.markdown(f"- {o['type']}: {o['detail']} ([source]({o['source']}))")
        # Backend wording, shown as is (frontend never writes its own wording).
        if dec.get("pca_handoff"):
            st.markdown(dec["pca_handoff"])
    st.caption(dec["guardrail"])


def _proof(station: str | None, est: dict):
    """Accuracy: the backend's how-sure sentence over all tested winters, then one winter's check
    (hide the real station, estimate it from its neighbors, compare)."""
    if not station:
        return
    st.markdown(f"**How accurate is this?** {est['how_sure']}")
    st.caption(help_for("how_sure_by_station"))
    st.markdown("One of those winters, with this station hidden:")
    v = get("/validate", station_id=station)
    season = _season_label(v["season"])
    w, n = v["with_elevation_adjustment"], v["no_elevation_adjustment"]
    b1, b2, b3 = st.columns(3)
    b1.metric("Actual chill portions", f"{w['actual']['chill_portions']:.1f}", help=help_for("proof_actual"))
    b2.metric("Our estimate", f"{w['estimated']['chill_portions']:.1f}",
              f"{w['error']['chill_portions']:+.1f}", delta_color="off", help=help_for("proof_estimate"))
    b3.metric("Hourly error", f"{w['hourly_rmse_F']} °F", help=help_for("proof_hourly_error"))
    # The shipped setting has no elevation adjustment (config.LAPSE_F_PER_M = 0), so both runs are identical.
    # Show the comparison only when the two numbers actually differ.
    if n["error"]["chill_portions"] != w["error"]["chill_portions"]:
        st.caption(f"Winter {season}. Without the elevation adjustment: {n['error']['chill_portions']:+.1f} portions.",
                   help=help_for("proof_no_elevation"))
    else:
        st.caption(f"Winter {season}.")
