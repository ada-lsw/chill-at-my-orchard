"""The CIMIS key is hidden in every message we log or print, and scripts don't load the web app to do it."""
import os
import subprocess
import sys
from pathlib import Path

from app import config, data

REPO = Path(__file__).resolve().parents[2]


def test_hide_key_replaces_the_key(monkeypatch):
    """Guard test: an error message that repeats the key is logged with *** instead."""
    monkeypatch.setattr(config, "CIMIS_APP_KEY", "FAKE-KEY-123")
    assert data.hide_key("CIMIS refused FAKE-KEY-123 today") == "CIMIS refused *** today"
    monkeypatch.setattr(config, "CIMIS_APP_KEY", "")
    assert data.hide_key("nothing to hide") == "nothing to hide"


def test_warm_cache_does_not_load_the_web_app(tmp_path):
    """scripts/warm_cache.py gets hide_key from data.py, so importing it doesn't build the FastAPI app."""
    code = ("import importlib.util, sys\n"
            f"spec = importlib.util.spec_from_file_location('warm_cache', r'{REPO / 'scripts' / 'warm_cache.py'}')\n"
            "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
            "print('app.main' in sys.modules)\n")
    env = {**os.environ, "CIMIS_APP_KEY": "", "DATA_SOURCE": "synthetic", "DATA_DIR": str(tmp_path)}
    run = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    assert run.stdout.strip().splitlines()[-1] == "False", run.stdout + run.stderr
