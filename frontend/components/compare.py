"""Compare tab: this season vs. past seasons, and the next 14 days.  Owner: Frontend B."""
from datetime import date

import plotly.graph_objects as go
import streamlit as st

CAPTION = ("Shaded band: where chill on each date counted as normal in past winters here. "
           "Dotted line: last winter. Dashed line: the next 14 days.")


def _grower_date(iso: str) -> str:
    """'2025-09-01' -> 'Sep 1', the way growers say dates (CLAUDE.md plain-language rules).

    Copied from glance.py on purpose: components don't import each other.
    """
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def _band_today(est: dict) -> tuple[float, float] | None:
    """The backend's normal band (low, high) on today's date, or None if it has no band for today.

    Index d of band_low/band_high means "d days after the chill start", like the curve,
    so today is the curve's last index. This only looks the value up; it computes nothing.
    """
    hist, curve = est["history"], est["chill"]["curve"]
    low, high = hist.get("band_low") or [], hist.get("band_high") or []
    i = len(curve) - 1
    if 0 <= i < len(low) and i < len(high) and low[i] is not None and high[i] is not None:
        return low[i], high[i]
    return None


def show(est: dict):
    """Three headline numbers, the chart, and a one-line key for the chart's lines."""
    ch, hist, proj = est["chill"], est["history"], est["projection"]
    p = hist["percentiles"].get("chill_portions", {})
    a1, a2, a3 = st.columns(3)
    a1.metric("Chill so far (portions)", f"{ch['chill_portions']:.0f}",
              help=f"Counted since {_grower_date(ch['start'])}")
    if p:
        band = _band_today(est)
        normal = f" Normal on this date: {band[0]:.0f} to {band[1]:.0f}." if band else ""
        a2.metric("vs. a typical year", f"{ch['chill_portions'] - p['p50']:+.0f}",
                  help=f"Typical on this date: {p['p50']:.0f}.{normal}")
    if "added" in proj:
        a3.metric("Next 14 days", f"+{proj['added']['chill_portions']:.0f}", help=f"Method: {proj['method']}")

    st.plotly_chart(build_chart(est), use_container_width=True)
    st.caption(CAPTION)


def _add_normal_band(fig: go.Figure, hist: dict):
    """Shade between the backend's band_low and band_high, skipping days that have no band (None).

    The backend puts the band edges exactly where the glance card's word changes (low / normal / high),
    so the chart and the card always agree. The frontend draws them as sent and computes nothing.
    Plotly's fill="tonexty" fills the area between this trace and the one added just before it.
    """
    low, high = hist.get("band_low") or [], hist.get("band_high") or []
    days = [d for d in range(min(len(low), len(high))) if low[d] is not None and high[d] is not None]
    if not days:
        return
    fig.add_trace(go.Scatter(x=days, y=[high[d] for d in days], mode="lines", line=dict(width=0),
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=days, y=[low[d] for d in days], mode="lines", line=dict(width=0),
                             fill="tonexty", fillcolor="rgba(120,120,120,0.25)",
                             name="Normal for this date", hoverinfo="skip"))


def build_chart(est: dict) -> go.Figure:
    """Build one chart: normal band, last winter, this winter, the target, and the next 14 days."""
    ch, hist, proj = est["chill"], est["history"], est["projection"]
    seasons = hist["seasons"]
    fig = go.Figure()
    _add_normal_band(fig, hist)

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
                      xaxis_title=f"Days since {_grower_date(ch['start'])}", yaxis_title="Chill portions",
                      legend=dict(orientation="h", y=-0.25), font=dict(size=14))
    return fig
