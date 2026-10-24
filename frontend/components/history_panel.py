"""Long view, "Is chill declining here?": season-end chill for past seasons, a trend, and research context.

Owner: Frontend B (Drew). Ported from the climate-trend section in PR #3.
"""
import numpy as np
import plotly.graph_objects as go
import streamlit as st

from api import get

BAR_COLOR = "#1f6f8b"
TREND_COLOR = "#c0392b"


def describe_trend(cp_per_decade, typical):
    """Turn the trend into one plain sentence for a grower.

    cp_per_decade: change in season-end chill portions per decade, from /history's trend line.
    typical: the median season-end chill portions across the seasons shown, for scale.
    Returns a short sentence, e.g. "Chill here has been falling about 4 portions per decade."
    """
    # TODO(human): decide what counts as "falling", "steady" or "rising", and return the sentence.
    return ""


def show(place: dict, est: dict):
    """Draw the long view: bars per season, the variety's target, a trend line, a sentence and a crop note."""
    h = get("/history", lat=place["lat"], lon=place["lon"], as_of=place["as_of"], max_seasons=15)
    if not h["seasons"]:
        st.info("No past seasons available here yet.")
        return

    st.subheader("Is chill declining here?")
    labels = [s["season"] for s in h["seasons"]]
    years = [int(s["season"][:4]) for s in h["seasons"]]
    cp = [s["chill_portions"] for s in h["seasons"]]

    fig = go.Figure(go.Bar(x=labels, y=cp, marker_color=BAR_COLOR, name="Season-end chill",
                           hovertemplate="%{x}: %{y:.0f} chill portions<extra></extra>"))
    t = est["target"]["target_cp"]
    fig.add_hline(y=t, line_dash="dash", annotation_text=f"{est['target']['variety']} needs {t:.0f}")
    if h["trend_cp_per_decade"] is not None:
        # Same straight-line fit the backend uses for trend_cp_per_decade, drawn across the bars.
        slope, intercept = np.polyfit(years, cp, 1)
        fig.add_trace(go.Scatter(x=labels, y=[slope * y + intercept for y in years], mode="lines",
                                 line=dict(color=TREND_COLOR, dash="dot", width=2), name="Trend",
                                 hoverinfo="skip"))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10), showlegend=False,
                      yaxis_title=f"Chill portions by {h['season_end']}")
    st.plotly_chart(fig, use_container_width=True)

    if h["trend_cp_per_decade"] is not None:
        sentence = describe_trend(h["trend_cp_per_decade"], float(np.median(cp)))
        if sentence:
            st.markdown(f"**{sentence}**")
        else:
            st.caption(f"Trend: {h['trend_cp_per_decade']:+.1f} chill portions per decade over {len(cp)} seasons.")
    st.caption(f"{len(cp)} seasons is a short record, so this trend is uncertain. "
               f"{get('/varieties')['climate_caption']}")

    v = get("/varieties")
    crop = v["varieties"].get(est["target"]["variety"], {}).get("crop")
    if crop in v["crop_context"]:
        st.info(v["crop_context"][crop])
