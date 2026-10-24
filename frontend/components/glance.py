"""The glance card: color, plain-word verdict, one number, what to do next.  Owner: Frontend A.

Uses the sentences the backend already wrote (est["summary"], dec["line"]) so wording always
matches the numbers.

Color-blind safe: no red/green pair. The verdict uses a warm / neutral / cool scale
(orange-red low, gray normal, blue high) and the decision status uses blue / amber / orange-red.
Both palettes were checked for protan, deutan and tritan color blindness. Color is never the
only cue: every box also has an icon (▼ ● ▲, ✓ ! ✗) and the backend's word in capitals, so it
still reads in grayscale or on a black-and-white printout.
"""
import os
from datetime import date
from html import escape
from urllib.parse import urlencode

import streamlit as st

INK = "#0b0b0b"   # text always stays dark; color only marks the edge and the icon

# Verdict band (est["verdict"]["band"]): how chill so far compares with past seasons on this date.
VERDICT_STYLE = {
    "low":     {"edge": "#c4441a", "fill": "#fbe9e2", "icon": "▼"},
    "normal":  {"edge": "#57564f", "fill": "#f0efec", "icon": "●"},
    "high":    {"edge": "#1f66c1", "fill": "#e4eefb", "icon": "▲"},
    "unknown": {"edge": "#57564f", "fill": "#f0efec", "icon": "?"},
}

# Decision status (dec["status"]): will the variety's target likely be reached in time?
# Every edge/icon color clears 3:1 contrast against its fill (amber was #c99500 at 2.40:1).
STATUS_STYLE = {
    "on_track": {"edge": "#1f66c1", "fill": "#e4eefb", "icon": "✓"},
    "done":     {"edge": "#1f66c1", "fill": "#e4eefb", "icon": "✓"},
    "watch":    {"edge": "#9a7100", "fill": "#fbf1d6", "icon": "!"},
    "at_risk":  {"edge": "#9e2a1b", "fill": "#f8e4e0", "icon": "✗"},
    "unknown":  {"edge": "#57564f", "fill": "#f0efec", "icon": "?"},
}


def _grower_date(iso: str) -> str:
    """'2026-02-21' -> 'Feb 21', the way growers say dates (CLAUDE.md plain-language rules)."""
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def _box(style: dict, word: str, sentence: str):
    """One glance box: a thick colored edge, an icon, the word in capitals, then the sentence.

    st.markdown with unsafe_allow_html lets us draw our own box instead of Streamlit's
    st.success / st.error, which are green and red. The backend's text is escaped first,
    so nothing in it can break the page.
    """
    st.markdown(
        f"""<div role="status" style="background:{style['fill']};border-left:12px solid {style['edge']};
                    border-radius:8px;padding:12px 16px;margin:6px 0;color:{INK};font-size:1.15rem">
              <span style="color:{style['edge']};font-weight:800;font-size:1.3rem">{style['icon']}</span>
              <b style="letter-spacing:.03em">{escape(word.upper())}.</b> {escape(sentence)}
            </div>""",
        unsafe_allow_html=True,
    )


def show(place: dict, est: dict, dec: dict):
    """Top of the screen, no scrolling needed."""
    st.subheader(place["label"])
    v, t = est["verdict"], est["target"]
    _box(VERDICT_STYLE.get(v["band"], VERDICT_STYLE["unknown"]),
         f"{v['band']} chill so far", est["summary"])
    _box(STATUS_STYLE.get(dec["status"], STATUS_STYLE["unknown"]),
         dec["status_words"], dec["line"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Chill so far", f"{t['progress_pct']:.0f}% of target",
              help=f"{est['chill']['chill_portions']:.0f} of {t['target_cp']:.0f} chill portions, counted since {_grower_date(est['chill']['start'])}")
    if dec.get("reached_in"):
        r = dec["reached_in"]
        c2.metric("Past years that reached the target", f"{r['seasons']} of {r['of']}",
                  help=f"By {_grower_date(dec['target_date'])}, adding each past season's weather to this season so far")
    w = dec.get("decision_window")
    if w and w.get("likely_between"):
        c3.metric(f"Reaches {w['milestone_cp']:.0f} chill portions", " to ".join(_grower_date(d) for d in w["likely_between"]),
                  help="When rest-breaking treatment decisions usually happen. Your PCA decides.")
    _share_link(place)


def _app_base_url() -> str | None:
    """The app's own web address, e.g. 'https://chill.streamlit.app/', or None if unknown.

    1. APP_URL, if set (the deployed Streamlit Cloud link).
    2. The browser's Origin header: exactly what the grower sees in the address bar.
       st.context.headers holds the headers the browser sent when it opened the page.
    3. The Host header (behind a proxy, X-Forwarded-Host), with https except on localhost.
    """
    if os.getenv("APP_URL"):
        return os.getenv("APP_URL").rstrip("/") + "/"
    headers = st.context.headers
    if headers.get("Origin"):
        return headers["Origin"].rstrip("/") + "/"
    host = headers.get("X-Forwarded-Host") or headers.get("Host")
    if not host:
        return None
    scheme = "http" if host.startswith(("localhost", "127.0.0.1")) else "https"
    return f"{scheme}://{host}/"


def _share_query(place: dict) -> str:
    """'?lat=..&lon=..&variety=..&as_of=..&label=..': what picker.py reads back to reopen this orchard."""
    q = {"lat": round(place["lat"], 4), "lon": round(place["lon"], 4), "variety": place["variety"],
         "as_of": place["as_of"], "label": place["label"]}
    if place.get("holdout_station"):
        q["holdout"] = place["holdout_station"]
    return "?" + urlencode(q)


def _share_link(place: dict):
    """A full link that reopens this exact orchard, for the grower to text their PCA.

    st.code shows the link with a copy button, so it pastes straight into a message.
    """
    base = _app_base_url()
    st.markdown("**Share with my PCA:** copy this link and send it in a text or email. "
                "It opens this orchard, variety and date.")
    if base:
        st.code(base + _share_query(place), language=None, wrap_lines=True)
    else:
        st.code(_share_query(place), language=None, wrap_lines=True)
        st.caption("Add this to the end of the app's web address.")
