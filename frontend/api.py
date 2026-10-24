"""The only place the frontend talks to the backend. Every screen part calls get().

Two ways to reach the backend:
- BACKEND_URL set (VS Code launch, docker-compose, `BACKEND_URL=http://localhost:8000 streamlit run app.py`):
  over HTTP to a separately running server.
- BACKEND_URL unset (Streamlit Community Cloud, or plain `streamlit run app.py`): "one-app mode". The backend
  runs inside this same process, called through FastAPI's TestClient, which calls the API's functions directly
  as if over HTTP, without a server. The answers are the same JSON either way.

Secrets: on Streamlit Cloud, Streamlit itself copies root-level entries of the app's secrets (CIMIS_APP_KEY,
DATA_SOURCE) into the environment before this file runs, so the backend's config.py reads them as usual.
"""
import os
import sys
from pathlib import Path

import requests
import streamlit as st

API = os.getenv("BACKEND_URL")                       # unset or empty: one-app mode
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"


@st.cache_resource(show_spinner=False)
def _backend():
    """The FastAPI app in this process, behind a TestClient. Built once per server, only in one-app mode.

    backend/ goes FIRST on the import path: `streamlit run app.py` puts frontend/ first, and frontend/app.py
    would otherwise be found when the backend imports its own package `app`.
    """
    sys.path.insert(0, str(BACKEND_DIR))
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)   # a backend error becomes a 500, as over HTTP


@st.cache_data(show_spinner=False)
def get(path: str, **params):
    """GET a backend endpoint and return its JSON. Cached, so reruns don't refetch.

    See http://localhost:8000/docs for every endpoint and the exact fields it returns.
    """
    params = {k: v for k, v in params.items() if v is not None}   # like requests: a None value is left out
    if API:
        r = requests.get(f"{API}{path}", params=params, timeout=300)
    else:
        r = _backend().get(path, params=params)
    r.raise_for_status()
    return r.json()
