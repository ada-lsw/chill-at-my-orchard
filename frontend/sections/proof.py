"""Accuracy proof: hide a real station, estimate it from its neighbors, and show the error."""
import streamlit as st

from api import get


def render(pin):
    """Show the hold-out check for demo orchards that have a station to hide. Does nothing otherwise."""
    station = pin.get("holdout_station")
    if not station:
        return
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
