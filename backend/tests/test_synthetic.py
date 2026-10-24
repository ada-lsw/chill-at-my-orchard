"""Synthetic weather must not depend on the model's elevation setting."""
import pandas as pd

from app import config, data


def test_synthetic_weather_ignores_the_model_lapse_setting(monkeypatch):
    """Changing LAPSE_F_PER_M (chosen by the validation table) must not change the made-up weather,
    so frontend teammates working on synthetic data keep seeing the same demo cards."""
    index = pd.date_range("2025-12-01", periods=48, freq="h")
    monkeypatch.setattr(config, "LAPSE_F_PER_M", 0.0)
    flat = data.synthetic_temp(35.5, -119.3, 400.0, index)
    monkeypatch.setattr(config, "LAPSE_F_PER_M", 0.0117)
    steep = data.synthetic_temp(35.5, -119.3, 400.0, index)
    assert (flat == steep).all()
