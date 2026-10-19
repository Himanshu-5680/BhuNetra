"""Heat target, features and time split. Everything here is CAUSAL (uses only data up to day t).

Leakage rules (tested in tests/test_phase3b.py):
  1. Features at day t use only days <= t (trailing windows, no centered windows).
  2. The climatological "normal" is learned from TRAIN years only.
  3. Rows whose target day falls in the next split are purged, so splits never overlap.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

KEY = ["district_id", "date"]


def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def day_of_year_365(date: pd.Series) -> pd.Series:
    """Day of year on a 365-day calendar so leap years do not shift later dates by one day."""
    d = date.dt.dayofyear
    leap_after_feb = date.dt.is_leap_year & (date.dt.month > 2)
    d = d - leap_after_feb.astype(int)
    return d.where(~((date.dt.month == 2) & (date.dt.day == 29)), 59)


def compute_normal(df: pd.DataFrame, train_end: str, half_window: int = 7) -> pd.DataFrame:
    """Mean Tmax per district and calendar day, smoothed over +/- half_window days, TRAIN years only."""
    tr = df[df["date"] <= pd.Timestamp(train_end)].copy()
    tr["doy"] = day_of_year_365(tr["date"])
    base = tr.groupby(["district_id", "doy"])["temperature_2m_max"].mean().unstack("doy")
    base = base.reindex(columns=range(1, 366))
    # circular smoothing: wrap the year so Dec/Jan windows are not cut off
    ext = pd.concat([base.iloc[:, -half_window:], base, base.iloc[:, :half_window]], axis=1)
    sm = ext.T.rolling(2 * half_window + 1, center=True, min_periods=1).mean().T.iloc[:, half_window:-half_window]
    sm.columns = base.columns
    return sm.stack().rename("tmax_normal").reset_index()


def label_heat(df: pd.DataFrame, normal: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Add tmax_normal, departure, heat, severe using the IMD-style rule (v1 simplifications in docs)."""
    h = cfg["heat"]
    out = df.copy()
    out["doy"] = day_of_year_365(out["date"])
    out = out.merge(normal, on=["district_id", "doy"], how="left")
    out["departure"] = out["temperature_2m_max"] - out["tmax_normal"]
    hot = out["temperature_2m_max"] >= h["region_min_tmax_c"]["plains"]   # all districts = plains in v1
    out["heat"] = (hot & ((out["departure"] >= h["departure_heat_wave_c"])
                          | (out["temperature_2m_max"] >= h["absolute_heat_wave_c"]))).astype(int)
    out["severe"] = (hot & ((out["departure"] > h["departure_severe_c"])
                            | (out["temperature_2m_max"] >= h["absolute_severe_c"]))).astype(int)
    return out


def make_features(df: pd.DataFrame) -> pd.DataFrame:
    """Trailing-window features per district. `df` must already have departure/heat from label_heat."""
    df = df.sort_values(KEY).reset_index(drop=True)
    g = df.groupby("district_id", sort=False)
    f = df[KEY].copy()
    f["tmax"] = df["temperature_2m_max"]
    f["tmin"] = df["temperature_2m_min"]
    f["apparent_max"] = df["apparent_temperature_max"]
    f["departure"] = df["departure"]
    f["tmax_normal"] = df["tmax_normal"]
    for k in (1, 2, 3):
        f[f"tmax_lag{k}"] = g["temperature_2m_max"].shift(k)
    f["departure_lag1"] = g["departure"].shift(1)
    f["tmax_mean3"] = g["temperature_2m_max"].transform(lambda s: s.rolling(3, min_periods=3).mean())
    f["tmax_mean7"] = g["temperature_2m_max"].transform(lambda s: s.rolling(7, min_periods=7).mean())
    f["tmax_trend3"] = f["tmax"] - f["tmax_lag3"]
    f["precip_sum7"] = g["precipitation_sum"].transform(lambda s: s.rolling(7, min_periods=7).sum())
    f["wind_max"] = df["wind_speed_10m_max"]
    f["heat_today"] = df["heat"]
    f["heat_days_last7"] = g["heat"].transform(lambda s: s.rolling(7, min_periods=7).sum())
    ang = 2 * np.pi * df["doy"] / 365.0
    f["doy_sin"], f["doy_cos"] = np.sin(ang), np.cos(ang)
    return f


def add_targets(f: pd.DataFrame, labelled: pd.DataFrame, horizons) -> pd.DataFrame:
    """heat_h{h} at issue day t = heat flag on day t+h. Rows without a future day get NaN (then dropped)."""
    lab = labelled.sort_values(KEY).reset_index(drop=True)
    g = lab.groupby("district_id", sort=False)
    out = f.copy()
    for h in horizons:
        out[f"heat_h{h}"] = g["heat"].shift(-h).values
    return out


def assign_split(issue_date: pd.Series, split_cfg: dict) -> pd.Series:
    """train / valid / test by issue day, 'purged' if the farthest target day crosses into the next split."""
    mh = max(split_cfg["horizons_days"])
    tr_end, va_end = pd.Timestamp(split_cfg["train_end"]), pd.Timestamp(split_cfg["valid_end"])
    reach = issue_date + pd.to_timedelta(mh, unit="D")
    s = pd.Series("test", index=issue_date.index)
    s[issue_date <= va_end] = "valid"
    s[issue_date <= tr_end] = "train"
    s[(issue_date <= tr_end) & (reach > tr_end)] = "purged"
    s[(issue_date > tr_end) & (issue_date <= va_end) & (reach > va_end)] = "purged"
    return s


def build_gold_heat(climate: pd.DataFrame, thresholds: dict, split_cfg: dict) -> pd.DataFrame:
    normal = compute_normal(climate, split_cfg["train_end"], thresholds["heat"]["normal_window_days"])
    lab = label_heat(climate, normal, thresholds)
    gold = add_targets(make_features(lab), lab, split_cfg["horizons_days"])
    gold["split"] = assign_split(gold["date"], split_cfg)
    targets = [f"heat_h{h}" for h in split_cfg["horizons_days"]]
    feats = [c for c in gold.columns if c not in KEY + targets + ["split"]]
    gold = gold.dropna(subset=feats + targets).reset_index(drop=True)   # first 7 days / last 3 days per district
    return gold
