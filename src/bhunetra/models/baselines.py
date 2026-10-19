"""Baselines every ML model must beat: persistence, climatology, seasonal-naive."""
from __future__ import annotations

import numpy as np
import pandas as pd

from bhunetra.features.heat import day_of_year_365


def persistence(df: pd.DataFrame) -> np.ndarray:
    """'Tomorrow is like today': predict heat on day t+h iff there is heat on day t."""
    return df["heat_today"].astype(float).to_numpy()


def _wsum(a: np.ndarray, half: int) -> np.ndarray:
    """Circular moving sum over +/- half days along axis 1 (wraps Dec into Jan)."""
    ext = np.concatenate([a[:, -half:], a, a[:, :half]], axis=1)
    k = np.ones(2 * half + 1)
    return np.apply_along_axis(lambda r: np.convolve(r, k, "valid"), 1, ext)


def climatology_fit(train: pd.DataFrame, h: int, by_district: bool, half: int = 7) -> dict:
    """P(heat on target day) by calendar day (+/- half days), from TRAIN rows only.

    by_district=False pools all districts, used when testing on places never seen in training.
    """
    tdoy = day_of_year_365(train["date"] + pd.Timedelta(days=h))
    g = train["district_id"].astype(str) if by_district else pd.Series("all", index=train.index)
    d = pd.DataFrame({"g": g.values, "doy": tdoy.values, "y": train[f"heat_h{h}"].values})
    cols = range(1, 366)
    ev = d.groupby(["g", "doy"])["y"].sum().unstack("doy").reindex(columns=cols, fill_value=0).fillna(0)
    ct = d.groupby(["g", "doy"])["y"].size().unstack("doy").reindex(columns=cols, fill_value=0).fillna(0)
    rate = _wsum(ev.to_numpy(float), half) / np.clip(_wsum(ct.to_numpy(float), half), 1, None)
    pooled = _wsum(ev.sum().to_numpy(float)[None, :], half) / np.clip(_wsum(ct.sum().to_numpy(float)[None, :], half), 1, None)
    return {"rate": pd.DataFrame(rate, index=ev.index, columns=list(cols)), "pooled": pooled[0],
            "by_district": by_district, "h": h}


def climatology_predict(model: dict, df: pd.DataFrame) -> np.ndarray:
    doy = day_of_year_365(df["date"] + pd.Timedelta(days=model["h"])).to_numpy() - 1
    if not model["by_district"]:
        return model["pooled"][doy]
    rate, out = model["rate"], model["pooled"][doy].copy()    # unseen district -> pooled rate
    pos = rate.index.get_indexer(df["district_id"].astype(str))
    seen = pos >= 0
    out[seen] = rate.to_numpy()[pos[seen], doy[seen]]
    return out


def seasonal_naive(df: pd.DataFrame, history: pd.DataFrame, h: int) -> np.ndarray:
    """Heat flag of the SAME district on the SAME calendar date one year before the target day.

    `history` is the full table (district_id, date, heat_today). Missing -> 0 (only happens for 2020).
    """
    look = history.set_index(["district_id", "date"])["heat_today"]
    tgt = (df["date"] + pd.Timedelta(days=h)) - pd.DateOffset(years=1)
    idx = pd.MultiIndex.from_arrays([df["district_id"].to_numpy(), tgt.to_numpy()])
    return look.reindex(idx).fillna(0).to_numpy(float)
