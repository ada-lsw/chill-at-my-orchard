"""The glance card: color, plain-word verdict, one number, what to do next.  Owner: Frontend A.

Uses the sentences the backend already wrote (est["summary"], dec["line"]) so wording always
matches the numbers. Color always comes with a word, for color-blind readers and printouts.
"""
from urllib.parse import urlencode

import streamlit as st

BOX = {"green": st.success, "yellow": st.warning, "red": st.error, "blue": st.info, "gray": st.info}


def show(place: dict, est: dict, dec: dict):
    """Top of the screen, no scrolling needed."""
    st.subheader(place["label"])
    v, t = est["verdict"], est["target"]
    BOX.get(v["color"], st.info)(f"**{v['band'].upper()} CHILL SO FAR.** {est['summary']}")
    BOX.get(dec["color"], st.info)(f"**{dec['status_words'].upper()}.** {dec['line']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Chill so far", f"{t['progress_pct']:.0f}% of target",
              help=f"{est['chill']['chill_portions']:.0f} of {t['target_cp']:.0f} chill portions, counted since {est['chill']['start']}")
    if dec.get("reached_in"):
        r = dec["reached_in"]
        c2.metric("Past years that reached the target", f"{r['seasons']} of {r['of']}",
                  help=f"By {dec['target_date']}, adding each past season's weather to this season so far")
    w = dec.get("decision_window")
    if w and w.get("likely_between"):
        c3.metric(f"Reaches {w['milestone_cp']:.0f} chill portions", " to ".join(d[5:] for d in w["likely_between"]),
                  help="When rest-breaking treatment decisions usually happen. Your PCA decides.")
    _share_link(place)


def _share_link(place: dict):
    """A link that reopens this exact orchard, for the grower to send their PCA."""
    q = {"lat": round(place["lat"], 4), "lon": round(place["lon"], 4), "variety": place["variety"],
         "as_of": place["as_of"], "label": place["label"]}
    if place.get("holdout_station"):
        q["holdout"] = place["holdout_station"]
    st.text_input("Share with my PCA (copy this link)", value="?" + urlencode(q),
                  help="Add it to the end of the app's web address. Opens this orchard with these settings.")
