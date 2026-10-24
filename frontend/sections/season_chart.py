"""This season's chill curve drawn over the past seasons' curves."""
import plotly.graph_objects as go
import streamlit as st


def render(est):
    """Draw this season (blue) against past seasons (gray), in chill portions since Nov 1."""
    fig = go.Figure()
    for s in est["history"]["seasons"]:
        fig.add_trace(go.Scatter(y=s["curve"], mode="lines", line=dict(color="lightgray", width=1),
                                 name=s["season"], hoverinfo="name+y", showlegend=False))
    fig.add_trace(go.Scatter(y=est["chill"]["curve"], mode="lines", line=dict(color="#1f6f8b", width=4),
                             name="This season"))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis_title="Days since Nov 1", yaxis_title="Chill portions",
                      title="This season (blue) vs. past seasons (gray)")
    st.plotly_chart(fig, use_container_width=True)
