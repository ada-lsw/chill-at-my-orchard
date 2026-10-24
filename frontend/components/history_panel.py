"""Long view, "Is chill declining here?": season-end chill for past seasons, a trend, and research context.

Owner: Frontend B (Drew). Ported from the climate-trend section in PR #3.
The backend fits the trend and words the sentence (/history trend_line, trend_sentence); this file only draws them.
"""
from datetime import date

import plotly.graph_objects as go
import streamlit as st

from api import get

BAR_COLOR = "#1f6f8b"
TREND_COLOR = "#52514e"   # dark gray: red would read as "bad" and is hard next to teal for color-blind viewers


def _grower_month_day(month_day: str) -> str:
    """'03-31' -> 'Mar 31', the way growers say dates (same style as glance.py's _grower_date).

    The year 2000 is only a placeholder; it is a leap year, so '02-29' works too.
    """
    d = date(2000, *map(int, month_day.split("-")))
    return f"{d:%b} {d.day}"


def _skipped_caption(skipped: list[dict]):
    """One small line saying how many winters the backend left out of the chart (it lists them in seasons_skipped).

    A count only: the backend decides which winters are skipped; nothing here is calculated.
    """
    n = len(skipped)
    if n:
        st.caption(f"{n} earlier winter{'s' if n != 1 else ''} had no saved data and "
                   f"{'are' if n != 1 else 'is'} not shown.")


def _how_to_read_caption(last_season: str, variety: str):
    """One small line explaining a bar label like '2024-25' and the dashed line, in grower words.

    The counting dates (Sep 1 to Mar 31) are already in the backend's trend sentence, so they aren't repeated.
    If the label isn't the usual 'YYYY-YY' shape, the example is skipped instead of guessing.
    """
    first_year = last_season.split("-")[0]
    example = (f': "{last_season}" means fall {first_year} into spring {int(first_year) + 1}'
               if first_year.isdigit() else "")
    st.caption(f"Each bar is one winter{example}. The dashed line is what {variety} needs.")


def show(place: dict, est: dict):
    """Draw the long view: bars per season, the variety's target, the backend's trend line, its sentence and a crop note."""
    h = get("/history", lat=place["lat"], lon=place["lon"], as_of=place["as_of"])
    if not h["seasons"]:
        st.info(h["trend_sentence"])   # the backend's "No past winters with saved data here yet."
        return

    v = get("/varieties")   # fetched once, used for the caption and the crop note below
    st.subheader("Is chill declining here?")
    fig = go.Figure(go.Bar(x=[s["season"] for s in h["seasons"]], y=[s["chill_portions"] for s in h["seasons"]],
                           marker_color=BAR_COLOR, name="Season-end chill",
                           hovertemplate="Winter %{x}: %{y:.0f} chill portions<extra></extra>"))
    t = est["target"]["target_cp"]
    # Label on the left, above the line: on a 375px phone a right-side label can run off the chart edge.
    fig.add_hline(y=t, line_dash="dash", annotation_text=f"{est['target']['variety']} needs {t:.0f}",
                  annotation_position="top left")
    line = h["trend_line"]
    # Draw the line only when the backend says the trend is clear (falling or rising). Otherwise a sloped line
    # would contradict the sentence below ("no clear rise or fall").
    if line and h.get("trend_direction") in ("falling", "rising"):
        ends = (line["start"], line["end"])   # the fitted straight line at the first and last season
        fig.add_trace(go.Scatter(x=[p["season"] for p in ends], y=[p["chill_portions"] for p in ends], mode="lines",
                                 line=dict(color=TREND_COLOR, dash="dot", width=2), name="Trend",
                                 hoverinfo="skip"))
    # type="category" keeps labels like "2024-25" as text, so Plotly never reads them as dates.
    # A short axis title fits a phone; the caption under the chart says what a bar means.
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10), showlegend=False,
                      xaxis_type="category",
                      yaxis_title=f"Chill by {_grower_month_day(h['season_end'])}")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})  # no tiny toolbar on phones (from Sevim's #10)

    _how_to_read_caption(h["seasons"][-1]["season"], est["target"]["variety"])
    st.markdown(f"**{h['trend_sentence']}**")
    _skipped_caption(h["seasons_skipped"])
    st.caption(v["climate_caption"])

    crop = v["varieties"].get(est["target"]["variety"], {}).get("crop")
    if crop in v["crop_context"]:
        st.info(v["crop_context"][crop])
