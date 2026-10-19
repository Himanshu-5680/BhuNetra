"""Data + prediction layer shared by the app, the NL query box and (later) the API.

Replay mode: we have real data up to 2024-12-31, so the app can show what the model would have said
on any 2024 day AND what actually happened. This is NOT live. Live mode needs fresh ingestion.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from bhunetra.features.heat import build_gold_heat, load_yaml
from bhunetra.models.default import fit_default, predict_default
from bhunetra.models.heat_pipeline import LR_FEATS

HORIZONS = (1, 2, 3)
# Okabe-Ito colour-blind-safe palette. High is ALSO bigger, so it never relies on colour alone.
BAND_STYLE = {"low": {"color": [0, 114, 178], "radius": 30000, "hex": "#0072B2"},
              "moderate": {"color": [240, 228, 66], "radius": 48000, "hex": "#F0E442"},
              "high": {"color": [213, 94, 0], "radius": 70000, "hex": "#D55E00"}}


def find_inputs(root: Path = Path(".")) -> dict:
    """Prefer fresh Silver tables; otherwise the bundled, labelled offline snapshot."""
    silver = root / "data/silver/climate_daily.parquet"
    if silver.exists() and (root / "data/silver/districts.parquet").exists():
        return {"mode": "silver", "climate": silver, "districts": root / "data/silver/districts.parquet", "meta": None}
    snap = root / "data/snapshots"
    if (snap / "climate_daily_2020_2024.parquet").exists():
        return {"mode": "snapshot", "climate": snap / "climate_daily_2020_2024.parquet",
                "districts": snap / "districts.parquet", "meta": json.loads((snap / "SNAPSHOT.json").read_text())}
    raise FileNotFoundError("No data found. Run `bhunetra ingest ...` + `bhunetra build`, or restore data/snapshots/.")


def band(p: float, cfg: dict) -> str:
    b = cfg["risk_bands"]
    return "low" if p < b["low_below"] else ("high" if p >= b["high_from"] else "moderate")


def build_replay(inputs: dict) -> dict:
    """Fit the default model per horizon (train+valid only) and score every 2024 day."""
    climate = pd.read_parquet(inputs["climate"])
    dist = pd.read_parquet(inputs["districts"])[["district_id", "name", "state", "lat", "lon"]]
    th, sp = load_yaml("configs/thresholds.yaml"), load_yaml("configs/split.yaml")
    gold = build_gold_heat(climate, th, sp)
    models = {h: fit_default(gold, f"heat_h{h}") for h in HORIZONS}
    te = gold[gold["split"] == "test"].copy()
    for h in HORIZONS:
        te[f"p{h}"] = predict_default(models[h], te)
    te = te.merge(dist, on="district_id", how="left")
    te["date"] = pd.to_datetime(te["date"])
    return {"table": te, "models": models,
            "data_through": str(climate["date"].max().date()),
            "fetched_range": (climate["fetched_at_utc"].min(), climate["fetched_at_utc"].max()),
            "n_districts": int(climate["district_id"].nunique())}


def contributions(model, row: pd.Series) -> pd.Series:
    """Per-feature push on the log-odds of heat for ONE row (exact for a linear model: coef * z-score)."""
    scaler, lr = model[0], model[1]
    x = row[LR_FEATS].astype(float).to_numpy()
    z = (x - scaler.mean_) / scaler.scale_
    return pd.Series(lr.coef_[0] * z, index=LR_FEATS)


def uncertainty_note(path: str = "reports/heat_uncertainty.csv") -> dict | None:
    """Typical width of the 80% Tmax interval (from the real 2024 evaluation), per horizon."""
    p = Path(path)
    if not p.exists():
        return None
    u = pd.read_csv(p).set_index("horizon_days")
    return {int(h): {"width": float(r["mean_width_conformal_C"]), "coverage": float(r["coverage_conformal"])} for h, r in u.iterrows()}
