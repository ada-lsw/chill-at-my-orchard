"""The only place the frontend talks to the backend. Every screen part calls get()."""
import os

import requests
import streamlit as st

API = os.getenv("BACKEND_URL", "http://localhost:8000")


@st.cache_data(show_spinner=False)
def get(path: str, **params):
    """GET a backend endpoint and return its JSON. Cached, so reruns don't refetch.

    See http://localhost:8000/docs for every endpoint and the exact fields it returns.
    """
    r = requests.get(f"{API}{path}", params=params, timeout=300)
    r.raise_for_status()
    return r.json()
