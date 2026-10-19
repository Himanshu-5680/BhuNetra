"""Historical daily weather (Open-Meteo Archive, ERA5-based). Resumable and rate-limit aware.

Open-Meteo's blog says calls with >14 days or >10 variables count as several calls (weight), with
10,000/day, 5,000/hour, 600/minute limits. The exact weighting formula is not documented, so we use
a conservative ESTIMATE (days/14 per location) to stop before the daily limit. Re-run next day to resume.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from bhunetra.net import DataUnavailable, fetch_to_bronze

URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARS = ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
              "apparent_temperature_max", "precipitation_sum", "wind_speed_10m_max"]
SOURCE = "open_meteo_history"
BATCH = 10  # locations per call; small so one failure loses little


def est_weight(days: int, n_loc: int, n_vars: int = len(DAILY_VARS)) -> float:
    return max(1.0, days / 14) * max(1.0, n_vars / 10) * n_loc


def _done_keys(bronze_dir: str | Path) -> set[tuple]:
    keys = set()
    for m in (Path(bronze_dir) / SOURCE).glob("*.meta.json"):
        meta = json.loads(m.read_text())
        keys.add((tuple(meta["district_ids"]), meta["params"]["start_date"], meta["params"]["end_date"]))
    return keys


def ingest_history(points: pd.DataFrame, first_year: int, last_year: int,
                   max_weight: float = 8000, pause_s: float = 1.0,
                   per_minute: float | None = 400, rate_wait_s: float = 70, max_rate_waits: int = 3,
                   bronze_dir: str | Path = "data/bronze", log=print, **kw) -> dict:
    done, spent, n_new, n_skip = _done_keys(bronze_dir), 0.0, 0, 0
    chunks = [points.iloc[i:i + BATCH] for i in range(0, len(points), BATCH)]
    for year in range(first_year, last_year + 1):
        start, end = f"{year}-01-01", f"{year}-12-31"
        days = 366 if year % 4 == 0 else 365
        for c in chunks:
            ids = tuple(c["district_id"])
            if (ids, start, end) in done:
                n_skip += 1; continue
            w = est_weight(days, len(c))
            if spent + w > max_weight:
                log(f"Stopped at budget (~{spent:.0f} of {max_weight:.0f} est. calls). Re-run to resume.")
                return {"new": n_new, "skipped": n_skip, "est_weight": spent, "complete": False}
            params = {"latitude": ",".join(f"{v:.4f}" for v in c["lat"]),
                      "longitude": ",".join(f"{v:.4f}" for v in c["lon"]),
                      "start_date": start, "end_date": end,
                      "daily": ",".join(DAILY_VARS), "timezone": "UTC"}
            waits = 0
            while True:
                try:
                    fetch_to_bronze(SOURCE, URL, params=params, bronze_dir=bronze_dir,
                                    extra_meta={"district_ids": list(ids)}, **kw)
                    break
                except DataUnavailable as e:
                    if e.status != 429:
                        raise
                    if waits >= max_rate_waits:  # still limited: stop honestly, progress is saved
                        log(f"Rate limit (429) persists after {waits} waits. Server said: {e.body}")
                        return {"new": n_new, "skipped": n_skip, "est_weight": spent,
                                "complete": False, "stopped": "rate_limit", "server_said": e.body}
                    waits += 1
                    log(f"429 rate limit: waiting {rate_wait_s:.0f}s then retrying ({waits}/{max_rate_waits})")
                    time.sleep(rate_wait_s)
            spent += w; n_new += 1
            log(f"{year} batch of {len(c)} ok (est. spent {spent:.0f})")
            # Pace requests: stay under `per_minute` estimated calls/min (limit is 600/min per docs).
            time.sleep(max(pause_s, w / per_minute * 60 if per_minute else 0))
    return {"new": n_new, "skipped": n_skip, "est_weight": spent, "complete": True}
