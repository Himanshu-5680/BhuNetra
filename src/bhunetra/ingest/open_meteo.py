"""Open-Meteo ingestion (forecast + air quality). Endpoints checked on official docs, Phase 1."""
from __future__ import annotations

import pandas as pd

from bhunetra.net import Fetched, fetch_to_bronze

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
FORECAST_VARS = ["temperature_2m", "relative_humidity_2m", "apparent_temperature",
                 "precipitation", "wind_speed_10m"]
AIR_VARS = ["pm2_5", "pm10", "nitrogen_dioxide", "ozone", "us_aqi"]
BATCH = 50  # points per request (Open-Meteo accepts comma-separated coordinates)


def _batches(points: pd.DataFrame, size: int = BATCH):
    for i in range(0, len(points), size):
        yield points.iloc[i : i + size]


def _call(source: str, url: str, chunk: pd.DataFrame, variables: list[str],
          past_days: int, forecast_days: int, **kw) -> Fetched:
    params = {
        "latitude": ",".join(f"{v:.4f}" for v in chunk["lat"]),
        "longitude": ",".join(f"{v:.4f}" for v in chunk["lon"]),
        "hourly": ",".join(variables),
        "past_days": past_days,
        "forecast_days": forecast_days,
        "timezone": "UTC",
    }
    return fetch_to_bronze(source, url, params=params,
                           extra_meta={"district_ids": list(chunk["district_id"])}, **kw)


def ingest_forecast(points: pd.DataFrame, past_days: int = 7, forecast_days: int = 3, **kw):
    """`points` needs columns: district_id, lat, lon. Returns list of Bronze files."""
    return [_call("open_meteo_forecast", FORECAST_URL, c, FORECAST_VARS, past_days, forecast_days, **kw)
            for c in _batches(points)]


def ingest_air_quality(points: pd.DataFrame, past_days: int = 7, forecast_days: int = 3, **kw):
    """CAMS *model* output (~45 km over India), not sensor readings."""
    return [_call("open_meteo_air", AIR_URL, c, AIR_VARS, past_days, forecast_days, **kw)
            for c in _batches(points)]
