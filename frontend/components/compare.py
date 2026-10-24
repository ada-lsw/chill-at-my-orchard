"""Compare tab: this season vs. past seasons, and the next 14 days.  Owner: Frontend B."""
import plotly.graph_objects as go
import streamlit as st


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

    fig = go.Figure()
    closest = est["verdict"].get("closest_season")
    for s in hist["seasons"]:
        is_closest = s["season"] == closest
        fig.add_trace(go.Scatter(y=s["curve"], mode="lines", name=s["season"],
                                 line=dict(color="#888" if is_closest else "lightgray",
                                           width=2 if is_closest else 1, dash="dot" if is_closest else None),
                                 showlegend=is_closest))
    fig.add_trace(go.Scatter(y=ch["curve"], mode="lines", line=dict(color="#1f6f8b", width=4), name="This season"))
    t = est["target"]["target_cp"]
    fig.add_hline(y=t, line_dash="dash", annotation_text=f"{est['target']['variety']} needs {t:.0f}")
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis_title=f"Days since {ch['start']}", yaxis_title="Chill portions")
    st.plotly_chart(fig, use_container_width=True)
