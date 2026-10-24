"""Talking to the backend. Every section imports `get` from here so all API calls share one cache."""
import os

import requests
import streamlit as st

API = os.getenv("BACKEND_URL", "http://localhost:8000")


@st.cache_data(show_spinner=False)
def get(path, **params):
    """GET a backend endpoint and return its JSON. Results are cached, so repeat calls are instant."""
    r = requests.get(f"{API}{path}", params=params, timeout=300)
    r.raise_for_status()
    return r.json()
