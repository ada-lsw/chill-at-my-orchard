"""Details layer ("Show the numbers"): every measure, accuracy, sources.  Owner: Frontend B."""
from datetime import date

import streamlit as st

from api import get

FEET_PER_METER = 3.28084


def grower_date(iso: str) -> str:
    """Show a date the way growers say it: "2025-09-01" becomes "Sep 1"."""
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def measure(col, label: str, value: str, meaning: str, model: str):
    """One measure: the number, a plain one-line meaning printed under it, and the model name in the tooltip.

    The meaning is printed, not hidden in a tooltip, because tooltips are hard to tap on a phone.
    """
    col.metric(label, value, help=model)
    col.caption(meaning)


def show(place: dict, est: dict, dec: dict):
    ch, g = est["chill"], est["gdd"]
    start = grower_date(ch["start"])
    m1, m2, m3, m4 = st.columns(4)
    measure(m1, "Chill portions", f"{ch['chill_portions']:.1f}",
            "The measure your variety's target uses. Warm afternoons can undo some of the chill.",
            "Dynamic Model. FNRIC calls it more a research tool than a rule.")
    measure(m2, "Chill hours", f"{ch['chill_hours']:.0f}",
            f"Hours between 32°F and 45°F since {start}. The older, simpler count.",
            "Chill Hours Model, 32°F < T ≤ 45°F (FNRIC's convention).")
    measure(m3, "Utah chill units", f"{ch['utah_units']:.0f}",
            "Cool hours add units, warm hours take them away.",
            "Utah Model, FNRIC's temperature bins.")
    measure(m4, "Heat since bloom", f"{g['total_c_days']:.0f}" if g["started"] else "Not yet",
            f"Warmth after bloom that moves the crop toward harvest. Counted from {grower_date(g['start'])}.",
            f"Growing degree days (GDD), single sine, 5-35°C, in °C·days. {grower_date(g['start'])} is an assumed bloom date.")
    elev_ft = est["location"]["elev_m"] * FEET_PER_METER
    st.caption(f"Counting since {start} · {ch['hours_missing']} missing hours · "
               f"estimated from {len(est['neighbors'])} nearby stations · elevation {elev_ft:,.0f} ft")

    st.markdown("**What low chill can do:** " + ", ".join(dec["low_chill_symptoms"]) + ".")
    if dec["options"]:
        st.markdown("**Options to raise with your PCA:**")
        for o in dec["options"]:
            st.markdown(f"- {o['type']}: {o['detail']} ([source]({o['source']}))")
    st.caption(dec["guardrail"])

    station = place.get("holdout_station")
    if station:
        st.markdown("**How accurate is this?** We hid the real station and estimated it from its neighbors.")
        v = get("/validate", station_id=station)
        w, n = v["with_elevation_adjustment"], v["no_elevation_adjustment"]
        b1, b2, b3 = st.columns(3)
        b1.metric("Actual chill portions", f"{w['actual']['chill_portions']:.1f}")
        b2.metric("Our estimate", f"{w['estimated']['chill_portions']:.1f}",
                  f"{w['error']['chill_portions']:+.1f}", delta_color="off")
        b3.metric("Hourly error", f"{w['hourly_rmse_F']} °F")
        first, last = (date.fromisoformat(d) for d in v["season"].split(" to "))
        st.caption(f"Winter checked: {grower_date(str(first))}, {first.year} to {grower_date(str(last))}, {last.year}. "
                   f"Without the elevation adjustment: {n['error']['chill_portions']:+.1f} portions.")
