"""Long-horizon view: season-end chill since the 1980s, for planting decisions.  Owner: Frontend B."""
import plotly.graph_objects as go
import streamlit as st

from api import get


def show(place: dict, est: dict):
    h = get("/history", lat=place["lat"], lon=place["lon"], as_of=place["as_of"], max_seasons=15)
    if not h["seasons"]:
        st.info("No past seasons available here yet.")
        return
    x = [s["season"] for s in h["seasons"]]
    y = [s["chill_portions"] for s in h["seasons"]]
    fig = go.Figure(go.Bar(x=x, y=y, marker_color="#1f6f8b", name="Season-end chill"))
    t = est["target"]["target_cp"]
    fig.add_hline(y=t, line_dash="dash", annotation_text=f"{est['target']['variety']} needs {t:.0f}")
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="Chill portions by Mar 31")
    st.plotly_chart(fig, use_container_width=True)
    if h["trend_cp_per_decade"] is not None:
        st.caption(f"Trend: {h['trend_cp_per_decade']:+.1f} chill portions per decade "
                   f"over {len(x)} seasons. Short records make trends uncertain.")
