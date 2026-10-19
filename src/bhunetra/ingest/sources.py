"""Real-source fetchers. Each returns the bronze path. Endpoints from configs/sources.yaml."""
from __future__ import annotations
from pathlib import Path
from .http import fetch
from .bronze import write_bronze

WEATHER_VARS = ["temperature_2m", "relative_humidity_2m", "apparent_temperature",
                "precipitation", "wind_speed_10m"]
AQ_VARS = ["pm2_5", "pm10", "nitrogen_dioxide", "ozone", "us_aqi"]
# Rough India bounding box. Neighbouring countries are included; silver clips to districts.
INDIA_BBOX = dict(minlatitude=6.0, maxlatitude=37.5, minlongitude=68.0, maxlongitude=97.5)


def fetch_weather(root: Path, district_id: str, lat: float, lon: float,
                  past_days: int = 7, forecast_days: int = 3) -> Path:
    url = "https://api.open-meteo.com/v1/forecast"
    p = dict(latitude=lat, longitude=lon, hourly=",".join(WEATHER_VARS),
             past_days=past_days, forecast_days=forecast_days, timezone="UTC")
    r = fetch(url, p)
    return write_bronze(root, "open_meteo_forecast", district_id, url, p, r.content, r.status_code)


def fetch_air_quality(root: Path, district_id: str, lat: float, lon: float,
                      past_days: int = 7, forecast_days: int = 3) -> Path:
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    p = dict(latitude=lat, longitude=lon, hourly=",".join(AQ_VARS),
             past_days=past_days, forecast_days=forecast_days, timezone="UTC")
    r = fetch(url, p)
    return write_bronze(root, "open_meteo_air_quality", district_id, url, p, r.content, r.status_code)


def fetch_earthquakes(root: Path, start: str, end: str, min_mag: float = 2.5) -> Path:
    url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    p = dict(format="geojson", starttime=start, endtime=end, minmagnitude=min_mag,
             eventtype="earthquake", orderby="time", **INDIA_BBOX)
    r = fetch(url, p)
    return write_bronze(root, "usgs_earthquakes", f"{start}_{end}", url, p, r.content, r.status_code)
