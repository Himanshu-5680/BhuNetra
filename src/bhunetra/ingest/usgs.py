"""USGS earthquake catalog. Context only: earthquakes cannot be predicted."""
from __future__ import annotations

from bhunetra.net import Fetched, fetch_to_bronze

URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
# Rough bounding box around India + neighbourhood (documented in docs/targets.md in Phase 3).
INDIA_BBOX = dict(minlatitude=6, maxlatitude=37.5, minlongitude=68, maxlongitude=98)


def ingest_earthquakes(start: str, end: str, min_magnitude: float = 2.5, **kw) -> Fetched:
    params = {"format": "geojson", "starttime": start, "endtime": end,
              "minmagnitude": min_magnitude, "orderby": "time", "limit": 20000, **INDIA_BBOX}
    return fetch_to_bronze("usgs_earthquakes", URL, params=params, **kw)
