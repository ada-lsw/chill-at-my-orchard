"""Details layer ("Show the numbers"): every measure, accuracy, sources.  Owner: Frontend B."""
import streamlit as st

from api import get


def show(place: dict, est: dict, dec: dict):
    ch = est["chill"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Chill portions", f"{ch['chill_portions']:.1f}", help="Dynamic Model. FNRIC calls it more a research tool than a rule.")
    m2.metric("Chill hours (32-45°F)", f"{ch['chill_hours']:.0f}")
    m3.metric("Utah chill units", f"{ch['utah_units']:.0f}", help="Warm hours subtract units")
    g = est["gdd"]
    m4.metric("GDD since bloom", f"{g['total_c_days']:.0f}" if g["started"] else "Not yet",
              help=f"Single sine, 5-35°C, from {g['start']} (assumed bloom date)")
    st.caption(f"Counting since {ch['start']} · {ch['hours_missing']} missing hours · "
               f"estimated from {len(est['neighbors'])} nearby stations · elevation {est['location']['elev_m']} m")

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
        st.caption(f"Season {v['season']}. Without the elevation adjustment: {n['error']['chill_portions']:+.1f} portions.")
