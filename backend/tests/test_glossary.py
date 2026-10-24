"""/glossary: one plain line for every number the Details layer shows (work package G3)."""
import os
import re
from pathlib import Path

os.environ.setdefault("DATA_SOURCE", "synthetic")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
DETAILS = Path(__file__).resolve().parents[2] / "frontend" / "components" / "details.py"

# Every measure the Details layer explains (G3 "done when": every number has a plain explanation).
REQUIRED = {
    "chill_start", "chill_portions", "chill_hours", "hours_lt_45", "utah_units", "gdd",
    "custom_below", "custom_between", "custom_above", "hours_missing", "neighbors", "elevation",
    "proof_actual", "proof_estimate", "proof_hourly_error", "proof_no_elevation",
}
# The PCA guardrail: explanations never talk about rates, mixes, application or timing of a treatment.
BANNED = re.compile(r"\b(rate|rates|mix|mixes|apply|application|spray)\b", re.IGNORECASE)


def measures() -> dict:
    """The /glossary response's measures dict."""
    r = client.get("/glossary")
    assert r.status_code == 200, r.text
    return r.json()["measures"]


def keys_used_by_details() -> set[str]:
    """Keys details.py looks up, written as help_for("key") in that file."""
    return set(re.findall(r'help_for\("([a-z0-9_]+)"\)', DETAILS.read_text()))


def test_glossary_has_every_required_measure():
    assert REQUIRED <= set(measures())


def test_glossary_has_every_key_details_uses():
    used = keys_used_by_details()
    assert used, "details.py should look its explanations up with help_for(...)"
    assert used <= set(measures())


def test_each_explanation_is_one_plain_line():
    for key, line in measures().items():
        assert isinstance(line, str) and line.strip(), key
        assert "\n" not in line and len(line) <= 220, key
        assert not BANNED.search(line), f"{key}: {line}"
