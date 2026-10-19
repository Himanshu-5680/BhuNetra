"""District table: representative point, state, and a reproducible stratified study sample.

Why not the centroid? For curved/concave districts the centroid can fall OUTSIDE the shape.
shapely's representative_point() is always inside the polygon.
Join on district_id (shapeID), never on name: 7 district names repeat in geoBoundaries ADM2.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import Point, shape
from shapely.strtree import STRtree


def load_districts(geojson_path: str | Path) -> list[dict]:
    """geoBoundaries ADM2 GeoJSON -> [{district_id, name, lat, lon}]. Coordinates are NOT rounded."""
    feats = json.loads(Path(geojson_path).read_text())["features"]
    out = []
    for i, f in enumerate(feats):
        p = f["properties"]
        pt = shape(f["geometry"]).representative_point()
        out.append({"district_id": str(p.get("shapeID", i)), "name": p.get("shapeName", ""),
                    "lat": pt.y, "lon": pt.x})
    return out


def assign_states(d: pd.DataFrame, adm1_geojson: str | Path) -> pd.DataFrame:
    """Add a `state` column by point-in-polygon against ADM1.

    A point that falls in no state polygon (e.g. simplified-coast gaps) gets state=NaN. We do
    NOT guess a nearest state: unassigned rows are reported so a human can look at them.
    """
    feats = json.loads(Path(adm1_geojson).read_text())["features"]
    geoms = [shape(f["geometry"]) for f in feats]
    names = [f["properties"].get("shapeName") for f in feats]
    tree = STRtree(geoms)
    states = []
    for lon, lat in zip(d["lon"], d["lat"]):
        hit = tree.query(Point(lon, lat), predicate="within")
        states.append(names[int(hit[0])] if len(hit) else None)
    out = d.copy()
    out["state"] = states
    return out


def stratified_sample(d: pd.DataFrame, n_total: int, seed: int = 42) -> pd.Series:
    """Boolean mask (aligned to d.index) of ~n_total districts spread over states.

    Every state with an assigned district gets at least 1; the rest is proportional to the
    state's district count (largest remainder). Fixed seed -> identical sample every run.
    Rows with no state are never sampled.
    """
    ok = d[d["state"].notna()]
    sizes = ok.groupby("state").size()
    n_total = max(n_total, len(sizes))                       # can't have fewer than 1 per state
    ideal = sizes / sizes.sum() * n_total
    quota = np.maximum(1, np.floor(ideal)).astype(int)
    for s in (ideal - quota).sort_values(ascending=False).index:   # top up by biggest remainder
        if quota.sum() >= n_total:
            break
        if quota[s] < sizes[s]:
            quota[s] += 1
    rng = np.random.default_rng(seed)
    picked = []
    for s in sorted(sizes.index):
        idx = sorted(ok.index[ok["state"] == s])
        picked += list(rng.choice(idx, size=min(int(quota[s]), len(idx)), replace=False))
    return d.index.to_series().isin(picked)
