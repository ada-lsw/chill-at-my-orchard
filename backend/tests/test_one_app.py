"""One-app mode: with BACKEND_URL unset, the frontend calls the backend in the same process (no server).

Needs Streamlit, which CI doesn't install (it installs backend/requirements.txt only), so CI skips this
file. Runs on synthetic data with a blank key, never the real key from .env.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

os.environ["DATA_SOURCE"] = "synthetic"
os.environ["CIMIS_APP_KEY"] = ""
os.environ.pop("BACKEND_URL", None)

import pytest  # noqa: E402

pytest.importorskip("streamlit")

from fastapi.testclient import TestClient  # noqa: E402

from app import config, main  # noqa: E402

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
sys.path.insert(1, str(FRONTEND))        # after backend/, so `app` stays the backend package here
import api  # noqa: E402

KERN = config.DEMO_ORCHARDS["kern"]
PARAMS = {"lat": KERN["lat"], "lon": KERN["lon"], "as_of": KERN["as_of"], "variety": KERN["variety"],
          "exclude": [KERN["holdout_station"]], "history_seasons": 3}


@pytest.fixture(autouse=True)
def fresh_cache():
    """api.get remembers answers (st.cache_data) for the whole session; start each test empty."""
    api.get.clear()
    yield
    api.get.clear()


def test_one_app_mode_gives_the_same_json_as_the_api(monkeypatch):
    monkeypatch.setattr(api, "API", None)
    direct = TestClient(main.app).get("/estimate", params=PARAMS)
    assert direct.status_code == 200
    assert api.get("/estimate", **PARAMS) == direct.json()


def test_a_missing_value_is_left_out_like_over_http(monkeypatch):
    """requests drops a parameter whose value is None; one-app mode must do the same (not send 'as_of=')."""
    sent = []

    class Recorder:
        def get(self, path, params):
            sent.append(params)
            return TestClient(main.app).get(path, params=params)

    monkeypatch.setattr(api, "API", None)
    monkeypatch.setattr(api, "_backend", lambda: Recorder())
    api.get("/estimate", **{**PARAMS, "range_low_f": None})
    assert sent and "range_low_f" not in sent[0]


def test_backend_url_still_means_http(monkeypatch):
    """Guard test: with BACKEND_URL set (VS Code, docker-compose), the frontend calls the server as before."""
    asked = []

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    monkeypatch.setattr(api, "API", "http://backend.example:8000")
    monkeypatch.setattr(api.requests, "get", lambda url, params, timeout: asked.append(url) or Reply())
    assert api.get("/health") == {"ok": True}
    assert asked == ["http://backend.example:8000/health"]


APPTEST = textwrap.dedent("""
    import sys
    sys.path.insert(0, ".")                     # like `streamlit run app.py` from frontend/
    from streamlit.testing.v1 import AppTest
    for word in ("Durham", "Kern"):
        at = AppTest.from_file("app.py", default_timeout=300).run()
        next(b for b in at.button if word in str(b.label)).click().run()
        texts = [m.value for m in list(at.success) + list(at.warning) + list(at.info) + list(at.error)]
        assert not at.exception, [e.value for e in at.exception]
        # A red box is fine when it is the glance card itself (an "AT RISK" or "LOW CHILL" verdict starts with its bold
        # word); any other red box is an error message, which must not appear.
        assert not [e.value for e in at.error if not e.value.startswith("**")], [e.value for e in at.error]
        assert any("CHILL SO FAR" in t for t in texts), texts
        assert any(word in h.value for h in at.subheader)
    print("BOTH DEMOS OK")
""")


def test_both_demo_buttons_work_in_one_app_mode(tmp_path):
    """The real app, BACKEND_URL unset, both demo buttons: no exceptions, no red errors, glance card shown."""
    env = {k: v for k, v in os.environ.items() if k != "BACKEND_URL"}
    env.update(DATA_SOURCE="synthetic", CIMIS_APP_KEY="", DATA_DIR=str(tmp_path))
    run = subprocess.run([sys.executable, "-c", APPTEST], cwd=FRONTEND, env=env, capture_output=True, text=True,
                         timeout=600)
    assert "BOTH DEMOS OK" in run.stdout, run.stdout[-2000:] + run.stderr[-2000:]


def test_a_backend_error_is_not_hidden_in_one_app_mode(monkeypatch):
    """A crash in the backend surfaces as the real error (and in the server log), not a bare 500."""
    monkeypatch.setattr(api, "API", None)

    def broken(*args, **kwargs):
        raise RuntimeError("backend broke here")

    monkeypatch.setattr(main, "resolve_variety", broken)
    with pytest.raises(RuntimeError, match="backend broke here"):
        api.get("/estimate", **PARAMS)
