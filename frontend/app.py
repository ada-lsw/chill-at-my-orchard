"""Chill at My Orchard — grower-facing app. Talks to the backend API only."""
import os
from datetime import date

import folium
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_folium import st_folium

API = os.getenv("BACKEND_URL", "http://localhost:8000")
st.set_page_config(page_title="Chill at My Orchard", layout="wide")


@st.cache_data(show_spinner=False)
def get(path, **params):
    r = requests.get(f"{API}{path}", params=params, timeout=300)
    r.raise_for_status()
    return r.json()


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

# ---------------------------------------------------------------- chart
fig = go.Figure()
for s in hist["seasons"]:
    fig.add_trace(go.Scatter(y=s["curve"], mode="lines", line=dict(color="lightgray", width=1),
                             name=s["season"], hoverinfo="name+y", showlegend=False))
fig.add_trace(go.Scatter(y=ch["curve"], mode="lines", line=dict(color="#1f6f8b", width=4), name="This season"))
fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                  xaxis_title="Days since Nov 1", yaxis_title="Chill portions",
                  title="This season (blue) vs. past seasons (gray)")
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------- proof
station = pin.get("holdout_station")
if station:
    with st.expander("How accurate is this? (we hid the real station and estimated it)", expanded=True):
        v = get("/validate", station_id=station)
        w, n = v["with_elevation_adjustment"], v["no_elevation_adjustment"]
        b1, b2, b3 = st.columns(3)
        b1.metric("Actual chill portions", f"{w['actual']['chill_portions']:.1f}")
        b2.metric("Our estimate", f"{w['estimated']['chill_portions']:.1f}",
                  f"{w['error']['chill_portions']:+.1f} error", delta_color="off")
        b3.metric("Hourly error (RMSE)", f"{w['hourly_rmse_F']} °F")
        st.caption(f"Season {v['season']}. Without elevation adjustment: "
                   f"{n['error']['chill_portions']:+.1f} portions error. "
                   f"Neighbors: {', '.join(x['station_id'] for x in w['neighbors'])}")

st.caption("Data: CIMIS (California DWR), Open-Meteo. Chill models as used by UC Davis FNRIC.")
