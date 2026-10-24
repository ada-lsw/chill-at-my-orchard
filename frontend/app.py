"""Chill at My Orchard: the grower-facing app. Talks to the backend API only.

Layout (team plan, "glance first, details on request"):
  picker   -> which orchard          components/picker.py         Frontend A
  glance   -> verdict + decision     components/glance.py         Frontend A
  Compare  -> vs. past years         components/compare.py        Frontend B
  Long view-> since the 1980s        components/history_panel.py  Frontend B
  Details  -> the numbers and proof  components/details.py        Frontend B
This file only wires them together. Keep logic in the components.
"""
import streamlit as st

from api import get
from components import compare, details, glance, history_panel, picker

st.set_page_config(page_title="Chill at My Orchard", layout="wide")
# Phone screens only (up to 640px wide): less empty space at the top and smaller headings, so the
# glance card shows without scrolling (work package F2). Desktop keeps Streamlit's normal look.
st.markdown("""<style>
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"], .block-container { padding-top: 2rem !important; }
  h1 { font-size: 1.6rem !important; padding-bottom: 0.25rem !important; }
  h3 { font-size: 1.2rem !important; }
  .glance-box { font-size: 1rem !important; padding: 6px 12px !important; line-height: 1.35 !important; }
  /* Narrow phones (360px): tighter gaps between blocks and slimmer demo buttons, so both glance boxes fit. */
  [data-testid="stVerticalBlock"] { gap: 0.4rem !important; }
  .stButton button { padding-top: 0.2rem !important; padding-bottom: 0.2rem !important; min-height: 0 !important; }
  [data-testid="stWidgetLabel"] { min-height: 0 !important; margin-bottom: 0 !important; }
}
</style>""", unsafe_allow_html=True)
st.title("Chill at My Orchard")
st.caption("Chill for your own orchard, even where the weather station is far away or gone.")

# Labels for the parts of the page, named for who each part is for. The guide below uses the same words.
LONG_TAB = "Long-term view (for planning)"
NUMBERS_BOX = "For your PCA or consultant: every number, how sure we are, options"
SHARE_BOX = "Share my data"   # kept as is: tests/test_one_app.py looks for this exact label
# "Find what you need": one short line per group, so each knows where to look (fits a phone screen).
st.markdown(
    "**Find what you need**\n"
    "- **Growers:** will my trees bloom on time, and do I need to act? See the box at the top.\n"
    "- **No station nearby:** the chill is estimated for your own orchard. "
    f"How close it usually is: \"{NUMBERS_BOX}\".\n"
    f"- **PCAs and consultants:** the numbers behind the answer are in \"{NUMBERS_BOX}\"; "
    f"growers can send them with \"{SHARE_BOX}\".\n"
    f"- **FNRIC and planners:** chill trends for picking varieties are in \"{LONG_TAB}\".")

place = picker.pick()
if not place:
    st.info("Pick a demo orchard or drop a pin to start.")
    st.stop()

params = dict(lat=place["lat"], lon=place["lon"], as_of=place["as_of"], variety=place["variety"],
              exclude=place["exclude"])
with st.spinner("Estimating temperatures at this orchard..."):
    est = get("/estimate", **params)
    dec = get("/decision", **params)

if est["data_source"] == "synthetic":
    st.warning("Showing SYNTHETIC test data. Set DATA_SOURCE=cimis for real numbers.")

glance.show(place, est, dec)

tab_compare, tab_long = st.tabs(["Compare with past years", LONG_TAB])
with tab_compare:
    compare.show(est)
with tab_long:
    history_panel.show(place, est)

with st.expander(NUMBERS_BOX):
    details.show(place, est, dec)

with st.expander(SHARE_BOX):
    glance.share_link(place)   # a link that reopens this orchard, for a PCA, consultant or anyone else

st.caption("Data: CIMIS (California DWR), FNRIC chill models (UC Davis), Open-Meteo. "
           "Decision support informs; a licensed PCA decides.")
