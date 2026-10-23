"""14-day hourly forecast from Open-Meteo (free, no key, non-commercial use).

Saves every successful forecast to the cache so the demo still works with Wi-Fi off.
"""
from __future__ import annotations

import json

import pandas as pd
import requests

from . import config


def hourly_forecast(lat: float, lon: float, days: int = 14) -> tuple[pd.Series, str]:
    """Returns (hourly °F series, source) where source is 'live' or 'cached'."""
    cache = config.CACHE_DIR / f"forecast_{lat:.2f}_{lon:.2f}.json"
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "hourly": "temperature_2m",
            "temperature_unit": "fahrenheit", "timezone": config.TIMEZONE,
            "forecast_days": days,
        }, timeout=15)
        r.raise_for_status()
        payload = r.json()
        cache.write_text(json.dumps(payload))
        source = "live"
    except Exception:
        if not cache.exists():
            return pd.Series(dtype=float), "unavailable"
        payload = json.loads(cache.read_text())
        source = "cached"
    h = payload["hourly"]
    s = pd.Series(h["temperature_2m"], index=pd.to_datetime(h["time"]), dtype=float)
    return s, source
