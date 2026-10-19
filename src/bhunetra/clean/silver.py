"""Bronze -> Silver: parse raw API JSON into tidy, validated, provenance-tagged tables."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from bhunetra.clean.schemas import air_schema, climate_daily_schema, quake_schema, weather_schema


def _meta(path: Path) -> dict:
    return json.loads(path.with_suffix(path.suffix + ".meta.json").read_text())


def parse_open_meteo(path: Path, district_ids: list[str], variables: list[str]) -> pd.DataFrame:
    """One Open-Meteo response -> long table. Response is a list when several points were sent."""
    raw = json.loads(path.read_text())
    blocks = raw if isinstance(raw, list) else [raw]
    if len(blocks) != len(district_ids):
        # Fail loudly: silent misalignment would put data on the wrong district.
        raise ValueError(f"{path.name}: {len(blocks)} blocks but {len(district_ids)} district ids")
    m = _meta(path)
    frames = []
    for did, b in zip(district_ids, blocks):
        h = b["hourly"]
        df = pd.DataFrame({"time_utc": pd.to_datetime(h["time"])})
        for v in variables:
            df[v] = pd.to_numeric(h[v], errors="coerce")  # KeyError if API dropped a variable
        df.insert(0, "district_id", did)
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["source"], out["fetched_at_utc"], out["sha256"] = m["source"], m["fetched_at_utc"], m["sha256"]
    return out


def parse_history(path: Path, district_ids: list[str], variables: list[str]) -> pd.DataFrame:
    """Archive response (daily) -> long table. Same alignment rule as parse_open_meteo."""
    raw = json.loads(path.read_text())
    blocks = raw if isinstance(raw, list) else [raw]
    if len(blocks) != len(district_ids):
        raise ValueError(f"{path.name}: {len(blocks)} blocks but {len(district_ids)} district ids")
    m = _meta(path)
    frames = []
    for did, b in zip(district_ids, blocks):
        d = b["daily"]
        df = pd.DataFrame({"date": pd.to_datetime(d["time"])})
        for v in variables:
            df[v] = pd.to_numeric(d[v], errors="coerce")
        df.insert(0, "district_id", did)
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["source"], out["fetched_at_utc"], out["sha256"] = m["source"], m["fetched_at_utc"], m["sha256"]
    return out


def parse_usgs(path: Path) -> pd.DataFrame:
    gj = json.loads(path.read_text())
    m = _meta(path)
    rows = []
    for f in gj["features"]:
        p, (lon, lat, depth) = f["properties"], f["geometry"]["coordinates"]
        rows.append({"event_id": f["id"], "time_utc": pd.to_datetime(p["time"], unit="ms"),
                     "lat": lat, "lon": lon, "depth_km": depth, "magnitude": p.get("mag"),
                     "place": p.get("place")})
    df = pd.DataFrame(rows, columns=["event_id", "time_utc", "lat", "lon", "depth_km", "magnitude", "place"])
    df["source"], df["fetched_at_utc"], df["sha256"] = m["source"], m["fetched_at_utc"], m["sha256"]
    return df


def write_silver(df: pd.DataFrame, schema, name: str, silver_dir: str | Path = "data/silver") -> Path:
    """Validate against the contract, then write Parquet. Raises SchemaError on any violation."""
    df = schema.validate(df, lazy=True)
    out = Path(silver_dir) / f"{name}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out


SCHEMAS = {"climate": climate_daily_schema, "weather": weather_schema, "air": air_schema, "quakes": quake_schema}
