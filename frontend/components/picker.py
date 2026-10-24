"""Where the grower says which orchard: demo buttons, variety, date, map pin.  Owner: Frontend A.

Reads a shared link's settings from the URL (?lat=..&lon=..&variety=..&as_of=..), so a link a
grower sends their PCA opens on the same orchard.
"""
from datetime import date

import folium
import streamlit as st
from streamlit_folium import st_folium

from api import get


def _from_url():
    q = st.query_params
    if "lat" in q and "lon" in q:
        return {"lat": float(q["lat"]), "lon": float(q["lon"]), "label": q.get("label", "Shared orchard"),
                "variety": q.get("variety"), "as_of": q.get("as_of"), "holdout_station": q.get("holdout")}
    return None


def pick() -> dict | None:
    """Show the picker. Returns {lat, lon, label, variety, as_of, exclude, range} or None."""
    demo = get("/demo")
    menu = get("/varieties")
    if "pin" not in st.session_state:
        st.session_state.pin = _from_url()

    cols = st.columns(len(demo) + 1)
    for col, (key, d) in zip(cols, demo.items()):
        if col.button(d["label"], use_container_width=True, type="primary"):
            st.session_state.pin = {**d, "key": key}

    pin = st.session_state.pin
    with cols[-1]:
        names = [n for c in menu["crop_order"] for n, v in menu["varieties"].items() if v["crop"] == c]
        default_var = (pin or {}).get("variety") or names[0]
        variety = st.selectbox("Crop and variety", names, index=names.index(default_var) if default_var in names else 0)
        default_day = date.fromisoformat((pin or {}).get("as_of") or "2026-02-01")
        as_of = st.date_input("Date to check", value=default_day,
                              help="Chill counts from Sept 1. Pick a past date to replay a season.")

    with st.expander("Or drop a pin on your own orchard", expanded=pin is None):
        m = folium.Map(location=[37.6, -120.6], zoom_start=6)
        for s in get("/stations"):
            folium.CircleMarker([s["lat"], s["lon"]], radius=4, tooltip=s["name"],
                                color="#555" if s.get("active", True) else "#c33").add_to(m)
        clicked = st_folium(m, height=380, use_container_width=True, key="map")
        st.caption("Gray dot: weather station still reporting. Red dot: station that closed.")
        if clicked and clicked.get("last_clicked"):
            ll = clicked["last_clicked"]
            st.session_state.pin = pin = {"lat": ll["lat"], "lon": ll["lng"], "label": "Your pin", "key": "pin"}

    if not pin:
        return None
    exclude = [pin["holdout_station"]] if pin.get("holdout_station") else []
    return {**pin, "variety": variety, "as_of": str(as_of), "exclude": exclude}
