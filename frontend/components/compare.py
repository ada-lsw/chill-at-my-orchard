"""Compare tab: this season vs. past seasons, and the next 14 days.  Owner: Frontend B."""
from datetime import date

import plotly.graph_objects as go
import streamlit as st


def grower_date(iso: str) -> str:
    """Turn "2025-09-01" into "Sep 1", the way growers say dates."""
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def show(est: dict):
    ch, hist, proj = est["chill"], est["history"], est["projection"]
    p = hist["percentiles"].get("chill_portions", {})
    a1, a2, a3 = st.columns(3)
    a1.metric("Chill so far (portions)", f"{ch['chill_portions']:.0f}", help=f"Since {ch['start']}")
    if p:
        a2.metric("vs. a typical year", f"{ch['chill_portions'] - p['p50']:+.0f}",
                  help=f"Typical on this date: {p['p50']}. Normal range {p['p10']}-{p['p90']}.")
    if "added" in proj:
        a3.metric("Next 14 days", f"+{proj['added']['chill_portions']:.0f}", help=f"Method: {proj['method']}")

    st.plotly_chart(build_chart(est), use_container_width=True)
    st.caption("Shaded band: a normal year for this date. Below it the card says low, above it high. "
               "Dotted line: last winter. Dashed line: the next 14 days, from the backend's forecast outlook.")


def build_chart(est: dict) -> go.Figure:
    """Build one chart: normal range, last winter, this winter, the target, and the next 14 days."""
    ch, hist, proj = est["chill"], est["history"], est["projection"]
    seasons = hist["seasons"]
    fig = go.Figure()

    # The backend sends the normal band per day, drawn where the glance card's word changes,
    # so the chart and the card always agree. A day with too few past winters is None (a gap).
    low, high = hist.get("band_low") or [], hist.get("band_high") or []
    if any(v is not None for v in low):
        days = list(range(len(low)))
        fig.add_trace(go.Scatter(x=days, y=high, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=days, y=low, mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor="rgba(120,120,120,0.25)", name="Normal range (most winters)",
                                 hoverinfo="skip"))

    if seasons:
        last = max(seasons, key=lambda s: s["season"])  # season labels like "2024-25" sort by year
        fig.add_trace(go.Scatter(y=last["curve"], mode="lines", name=f"Last winter ({last['season']})",
                                 line=dict(color="#444444", width=2, dash="dot")))

    fig.add_trace(go.Scatter(y=ch["curve"], mode="lines", name="This winter",
                             line=dict(color="#1f6f8b", width=4)))

    # Dashed extension: a straight line from today's total to the backend's 14-day outlook.
    added = proj.get("added", {}).get("chill_portions")
    if added is not None and ch["curve"]:
        x0 = len(ch["curve"]) - 1
        fig.add_trace(go.Scatter(x=[x0, x0 + proj.get("days", 14)], y=[ch["curve"][-1], ch["curve"][-1] + added],
                                 mode="lines", name="Next 14 days (outlook)",
                                 line=dict(color="#1f6f8b", width=4, dash="dash")))

    t = est["target"]["target_cp"]
    fig.add_hline(y=t, line_dash="dash", line_color="#d55e00", line_width=3,
                  annotation_text=f"{est['target']['variety']} needs {t:.0f}")
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis_title=f"Days since {grower_date(ch['start'])}", yaxis_title="Chill portions",
                      legend=dict(orientation="h", y=-0.25), font=dict(size=14))
    return fig
