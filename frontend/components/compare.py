"""Compare tab: this season vs. past seasons, and the next 14 days.  Owner: Frontend B."""
from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st

# Hover text per point, e.g. "Oct 15: 12 chill portions", with the line's name ("This winter") beside it.
HOVER = "%{x|%b %-d}: %{y:.0f} chill portions<extra>%{fullData.name}</extra>"


def show(est: dict):
    """Draw the Compare tab: two plain-word numbers, the season chart, and a key to read it."""
    ch, hist, proj = est["chill"], est["history"], est["projection"]
    p = hist["percentiles"].get("chill_portions", {})
    # "Chill so far" lives on the glance card above; repeating it here in other words confused readers.
    cp = ch["chill_portions"]
    started = grower_date(ch["start"])
    a2, a3 = st.columns(2)
    if p:
        a2.metric("Compared with a typical year", vs_typical(round(cp) - round(p["p50"])),  # same rounded numbers as the help text, so they agree
                  help=f"This winter: {cp:.0f} chill portions. A typical year has {p['p50']:.0f} "
                       f"by this date. Both counted since {started}.")
    source = outlook_source(proj)
    if "added" in proj:
        a3.metric("Next 14 days", f"about +{proj['added']['chill_portions']:.0f}",
                  help=f"Chill portions likely to be added over the next two weeks, {source}. "
                       f"{est['target']['variety']} needs {est['target']['target_cp']:.0f} in all.")

    # displayModeBar off: no tiny toolbar to tap by accident on a phone.
    st.plotly_chart(build_chart(est), use_container_width=True, config={"displayModeBar": False})
    st.caption(f"Gray band: a normal year for this date. Below it the card says low, above it high. "
               f"Dotted line: last winter. Dashed blue line: the next 14 days, {source}. "
               f"Orange line: what {est['target']['variety']} needs. Counting started {started}.")


def outlook_source(proj: dict) -> str:
    """Say where the 14-day outlook comes from, matching the backend's projection method.

    The backend uses the live weather forecast only when the date is today; for a past date (like the
    demos) it uses the middle of past winters. The caption must not claim a forecast that wasn't used.
    """
    if proj.get("method") == "forecast":
        return "from the weather forecast"
    return "based on past winters on these dates"


def grower_date(iso: str) -> str:
    """Show a date the way growers say it: "2025-09-01" becomes "Sep 1"."""
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def vs_typical(diff: float) -> str:
    """Show the gap to a typical year in words a grower reads at a glance, e.g. "3 below usual"."""
    if round(diff) == 0:
        return "About the same"
    return f"{abs(diff):.0f} {'below' if diff < 0 else 'above'} usual"


def season_dates(start_iso: str, n: int) -> list[date]:
    """Calendar dates for the first n days of the season, so the chart reads "Oct 15", not "day 44".

    Day 0 is the start date. Past winters are drawn on this winter's dates so they line up by date.
    """
    start = date.fromisoformat(start_iso)
    return [start + timedelta(days=i) for i in range(n)]


def build_chart(est: dict) -> go.Figure:
    """Build one chart: normal range, last winter, this winter, the target, and the next 14 days."""
    ch, hist, proj = est["chill"], est["history"], est["projection"]
    seasons = hist["seasons"]
    start = ch["start"]
    fig = go.Figure()

    # The backend sends the normal band per day, drawn where the glance card's word changes,
    # so the chart and the card always agree. A day with too few past winters is None (a gap).
    low, high = hist.get("band_low") or [], hist.get("band_high") or []
    if any(v is not None for v in low):
        days = season_dates(start, len(low))
        fig.add_trace(go.Scatter(x=days, y=high, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=days, y=low, mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor="rgba(120,120,120,0.25)", name="Normal range",
                                 hoverinfo="skip"))

    if seasons:
        last = max(seasons, key=lambda s: s["season"])  # season labels like "2024-25" sort by year
        fig.add_trace(go.Scatter(x=season_dates(start, len(last["curve"])), y=last["curve"], mode="lines",
                                 name=f"Last winter ({last['season']})", hovertemplate=HOVER,
                                 line=dict(color="#444444", width=2, dash="dot")))

    fig.add_trace(go.Scatter(x=season_dates(start, len(ch["curve"])), y=ch["curve"], mode="lines",
                             name="This winter", hovertemplate=HOVER,
                             line=dict(color="#1f6f8b", width=4)))

    # Dashed extension: a straight line from today's total to the backend's 14-day outlook.
    added = proj.get("added", {}).get("chill_portions")
    if added is not None and ch["curve"]:
        today = season_dates(start, len(ch["curve"]))[-1]
        fig.add_trace(go.Scatter(x=[today, today + timedelta(days=proj.get("days", 14))],
                                 y=[ch["curve"][-1], ch["curve"][-1] + added],
                                 mode="lines", name="Next 14 days", hovertemplate=HOVER,
                                 line=dict(color="#1f6f8b", width=4, dash="dash")))

    t = est["target"]["target_cp"]
    fig.add_hline(y=t, line_dash="dash", line_color="#d55e00", line_width=3,
                  annotation_text=f"{est['target']['variety']} needs {t:.0f}",
                  annotation_position="top left")
    # Legend under the chart: on a 375px phone a legend above it wraps over the lines.
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis_title="Chill portions", xaxis=dict(tickformat="%b %-d"),
                      legend=dict(orientation="h", yanchor="top", y=-0.12, x=0), font=dict(size=14))
    return fig
