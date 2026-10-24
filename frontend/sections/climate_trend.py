"""Is chill declining here? Chill by this date in each past season, with a trend line and research context."""
import numpy as np
import plotly.graph_objects as go
import streamlit as st

THIS_SEASON_COLOR = "#1f6f8b"   # same blue as the season chart
PAST_SEASON_COLOR = "lightgray"

# What published research says for each crop in the dropdown. Two sentences each, with the source.
CROP_CONTEXT = {
    "almond": (
        "Almonds need little chill (about 200–300 chill hours), so research expects chill to stay "
        "sufficient through this century (Pathak et al. 2018). Frost during bloom is the bigger risk to watch."
    ),
    "walnut": (
        "Walnuts need about 700 chill hours, among the most of California's nut crops. For crops needing "
        "700+ hours, only 23–46% of the Central Valley may stay suitable by mid-century (Pathak et al. 2018)."
    ),
    "prune": (
        "Prunes (plums) need about 900 chill hours (Jha & Pathak 2024). For crops needing 700+ hours, "
        "only 23–46% of the Central Valley may stay suitable by mid-century (Pathak et al. 2018)."
    ),
    "pistachio": (
        "Pistachios need about 1,000 chill hours (Jha & Pathak 2024). In low-chill years, male and female "
        "trees bloom out of sync, which cuts pollination and yield (Pathak et al. 2018)."
    ),
}


def season_start_year(label):
    """Turn a season label like '2024-25' into its start year, 2024."""
    return int(label.split("-")[0])


def describe_trend(slope_per_year, typical):
    """Turn the trend line's slope into one plain sentence for a grower.

    slope_per_year: change in chill portions (by this date) per season, from the fitted line.
    typical: the median chill portions by this date across past seasons, for scale.
    Returns a short sentence, e.g. "Chill by this date has been falling about 4 portions per decade."
    """
    # TODO(human): decide what counts as "falling", "steady" or "rising", and return the sentence.
    return ""


def render(est, crop):
    """Draw chill-by-this-date for each past season plus this one, a trend line, and research context."""
    seasons = sorted(est["history"]["seasons"], key=lambda s: season_start_year(s["season"]))
    if len(seasons) < 3:
        return  # too few past seasons to say anything about a trend

    years = [season_start_year(s["season"]) for s in seasons]
    portions = [s["at_date"]["chill_portions"] for s in seasons]
    hours = [s["at_date"]["chill_hours"] for s in seasons]

    years.append(int(est["chill"]["start"][:4]))  # this season's start year, e.g. 2025 for Nov 1 2025
    portions.append(est["chill"]["chill_portions"])
    hours.append(est["chill"]["chill_hours"])

    # Straight-line fit through all seasons: slope = change in chill portions per season.
    slope, intercept = np.polyfit(years, portions, 1)

    st.subheader("Is chill declining here?")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[f"{y}-{str(y + 1)[-2:]}" for y in years], y=portions,
        marker_color=[PAST_SEASON_COLOR] * (len(years) - 1) + [THIS_SEASON_COLOR],
        customdata=hours, hovertemplate="%{x}: %{y:.0f} portions · %{customdata:.0f} chill hours<extra></extra>",
        name="Chill by this date",
    ))
    fig.add_trace(go.Scatter(
        x=[f"{y}-{str(y + 1)[-2:]}" for y in years], y=[slope * y + intercept for y in years],
        mode="lines", line=dict(color="#c0392b", dash="dash", width=2), name="Trend", hoverinfo="skip",
    ))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10), showlegend=False,
                      yaxis_title="Chill portions by this date",
                      title=f"Chill by {est['as_of'][5:]} each season (this season in blue)")
    st.plotly_chart(fig, use_container_width=True)

    sentence = describe_trend(slope, float(np.median(portions[:-1])))
    if sentence:
        st.markdown(f"**{sentence}**")
    st.caption(f"{len(years)} seasons is a short record. Over 40 years (1979–2019), research shows chill "
               "falling across most of California (Zhang et al. 2021).")

    if crop in CROP_CONTEXT:
        st.info(CROP_CONTEXT[crop])
