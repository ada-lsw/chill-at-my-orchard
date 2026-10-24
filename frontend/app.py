"""Chill at My Orchard — grower-facing app. Talks to the backend API only.

This file is the page shell: pick a place, call /estimate, show the three answers,
then hand the result to each section in frontend/sections/ in page order.
"""
from datetime import date

import folium
import streamlit as st
from streamlit_folium import st_folium

from api import get
from sections import climate_trend, proof, season_chart

st.set_page_config(page_title="Chill at My Orchard", layout="wide")


# ---------------------------------------------------------------- pick a place
st.title("Chill at My Orchard")
st.caption("Chill and growing degree days for your own orchard, even where the weather station is far away or gone.")

demo = get("/demo")
if "pin" not in st.session_state:
    st.session_state.pin = None

c1, c2, c3 = st.columns([1, 1, 1])
if c1.button(demo["durham"]["label"], use_container_width=True, type="primary"):
    st.session_state.pin = {**demo["durham"], "key": "durham"}
if c2.button(demo["foothill"]["label"], use_container_width=True, type="primary"):
    st.session_state.pin = {**demo["foothill"], "key": "foothill"}
with c3:
    as_of = st.date_input("As of", value=date(2026, 2, 1),
                          help="Chill counting starts Nov 1. Pick a past date to replay a season.")
    crop = st.selectbox("Crop", ["almond", "walnut", "pistachio", "prune"])
    r1, r2 = st.columns(2)
    range_low = r1.number_input("Range low (°F)", value=32.0, step=1.0)
    range_high = r2.number_input("Range high (°F)", value=45.0, step=1.0)

with st.expander("Or drop a pin on your own orchard", expanded=st.session_state.pin is None):
    m = folium.Map(location=[38.6, -121.4], zoom_start=7)
    for s in get("/stations"):
        folium.CircleMarker([s["lat"], s["lon"]], radius=4, tooltip=s["name"],
                            color="#555" if s.get("active", True) else "#c33").add_to(m)
    clicked = st_folium(m, height=380, use_container_width=True, key="map")
    if clicked and clicked.get("last_clicked"):
        ll = clicked["last_clicked"]
        st.session_state.pin = {"lat": ll["lat"], "lon": ll["lng"], "label": "Your pin", "key": "pin"}

pin = st.session_state.pin
if not pin:
    st.info("Pick a demo orchard or drop a pin to start.")
    st.stop()

exclude = [pin["holdout_station"]] if pin.get("holdout_station") else []
with st.spinner("Estimating temperatures at this orchard..."):
    est = get("/estimate", lat=pin["lat"], lon=pin["lon"], as_of=str(as_of), crop=crop, exclude=exclude,
              range_low_f=range_low, range_high_f=range_high)

if est["data_source"] == "synthetic":
    st.warning("Showing SYNTHETIC test data. Set DATA_SOURCE=cimis for real numbers.")

st.subheader(pin["label"])
ch, hist, proj = est["chill"], est["history"], est["projection"]
p = hist["percentiles"].get("chill_portions", {})

# ---------------------------------------------------------------- the three answers
a1, a2, a3 = st.columns(3)
a1.metric("1 · Chill so far (portions)", f"{ch['chill_portions']:.0f}",
          help=f"Since {ch['start']}. Dynamic model, preferred for California's mild winters.")
if p:
    a2.metric("2 · vs. a typical year", f"{ch['chill_portions'] - p['p50']:+.0f}",
              help=f"Typical (median) on this date: {p['p50']}. Normal range {p['p10']}–{p['p90']}.")
if "added" in proj:
    a3.metric("3 · Next 14 days", f"+{proj['added']['chill_portions']:.0f}",
              help=f"Method: {proj['method']}")

cr = ch["custom_range"]
m1, m2, m3, m4 = st.columns(4)
m1.metric("Chill hours (32–45°F)", f"{ch['chill_hours']:.0f}")
m2.metric("Hours below 45°F", f"{ch['hours_lt_45']:.0f}")
m3.metric("Utah chill units", f"{ch['utah_units']:.0f}", help="Warm hours subtract units")
m4.metric("GDD since bloom (°C·days)",
          f"{est['gdd']['total_c_days']:.0f}" if est["gdd"]["started"] else "Not yet",
          help=f"Single sine, 5–35°C, counted from {est['gdd']['start']} (assumed bloom date)")

st.markdown(f"**Your temperature range, since {ch['start']}:** "
            f"{cr['hours_below']:.0f} hours at or below {cr['low_f']:.0f}°F · "
            f"{cr['hours_between']:.0f} hours between {cr['low_f']:.0f} and {cr['high_f']:.0f}°F · "
            f"{cr['hours_above']:.0f} hours above {cr['high_f']:.0f}°F")
st.caption(f"{ch['hours_missing']} missing hours · elevation {est['location']['elev_m']} m")

# ---------------------------------------------------------------- sections (one file each)
season_chart.render(est)
climate_trend.render(est, crop)
proof.render(pin)

st.caption("Data: CIMIS (California DWR), Open-Meteo. Chill models as used by UC Davis FNRIC.")
st.caption("Research: Jha & Pathak 2024, Commun. Earth Environ. 5:485 · Zhang et al. 2021, Sci. Total Environ. "
           "791:148025 · Pathak et al. 2018, Agronomy 8:25 · Parker et al. 2021, Sci. Total Environ. 762:143971")
