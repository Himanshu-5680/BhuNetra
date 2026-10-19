"""Phase 3b tests: heat rule, leakage controls, split purge.

SYNTHETIC frames below are TEST FIXTURES to check logic only. Tests marked real_* run on the real
Silver table when present (env BHUNETRA_REAL_CLIMATE or data/silver/climate_daily.parquet).
"""
import os

import numpy as np
import pandas as pd
import pytest

from bhunetra.features.heat import (add_targets, assign_split, build_gold_heat, compute_normal,
                                    day_of_year_365, label_heat, load_yaml, make_features)

TH = load_yaml("configs/thresholds.yaml")
SP = load_yaml("configs/split.yaml")
REAL = os.environ.get("BHUNETRA_REAL_CLIMATE") or ("data/silver/climate_daily.parquet"
                                                   if os.path.exists("data/silver/climate_daily.parquet") else None)


def _fixture(n_districts=2, start="2020-01-01", end="2024-12-31", seed=0):  # TEST FIXTURE
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, end)
    rows = []
    for k in range(n_districts):
        base = 30 + 8 * np.sin(2 * np.pi * (dates.dayofyear - 100) / 365)
        tmax = base + rng.normal(0, 2, len(dates))
        rows.append(pd.DataFrame({"district_id": f"D{k}", "date": dates, "temperature_2m_max": tmax,
                                  "temperature_2m_min": tmax - 10, "temperature_2m_mean": tmax - 5,
                                  "apparent_temperature_max": tmax + 2,
                                  "precipitation_sum": rng.gamma(0.3, 3, len(dates)),
                                  "wind_speed_10m_max": rng.gamma(4, 3, len(dates))}))
    return pd.concat(rows, ignore_index=True)


def _labelled(df):
    n = compute_normal(df, SP["train_end"], TH["heat"]["normal_window_days"])
    return label_heat(df, n, TH)


def test_heat_rule_hand_cases():
    """Hand-written cases of the documented IMD-style rule (not data)."""
    df = pd.DataFrame({"district_id": "X", "date": pd.date_range("2022-05-01", periods=6),
                       "temperature_2m_max": [41.0, 41.0, 45.5, 39.0, 47.5, 44.0]})
    normal = pd.DataFrame({"district_id": "X", "doy": day_of_year_365(df["date"]),
                           "tmax_normal": [36.0, 38.0, 45.5, 30.0, 47.5, 36.0]})
    out = label_heat(df, normal, TH)
    # dep 5.0 & >=40 -> heat | dep 3.0 -> no | >=45 absolute -> heat | 39 < 40 even with dep 9 -> no
    # >=47 -> severe | dep 8.0 at 44 -> heat and severe (dep > 6.4)
    assert out["heat"].tolist() == [1, 0, 1, 0, 1, 1]
    assert out["severe"].tolist() == [0, 0, 0, 0, 1, 1]


def test_leap_day_does_not_shift_calendar():
    d = pd.Series(pd.to_datetime(["2023-03-01", "2024-03-01", "2024-02-29", "2024-12-31", "2023-12-31"]))
    assert day_of_year_365(d).tolist() == [60, 60, 59, 365, 365]


def test_normal_ignores_post_train_years():
    """Leakage control 2: changing data AFTER train_end must not change the normal."""
    df = _fixture()
    n1 = compute_normal(df, SP["train_end"])
    df2 = df.copy()
    df2.loc[df2["date"] > pd.Timestamp(SP["train_end"]), "temperature_2m_max"] += 10
    n2 = compute_normal(df2, SP["train_end"])
    pd.testing.assert_frame_equal(n1, n2)


def _feat_equal_before(df, cutoff):
    full = make_features(_labelled(df))
    cut = make_features(_labelled(df[df["date"] <= cutoff]))
    a = full[full["date"] <= cutoff].reset_index(drop=True)
    b = cut.reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_features_are_causal_synthetic():
    """Leakage control 1: deleting every day after T leaves features up to T unchanged."""
    _feat_equal_before(_fixture(), pd.Timestamp("2023-06-30"))


def test_features_do_not_see_future_values():
    """Perturb only the future: features at/before T must not move."""
    df = _fixture()
    T = pd.Timestamp("2023-06-30")
    df2 = df.copy()
    fut = df2["date"] > T
    for c in ["temperature_2m_max", "temperature_2m_min", "apparent_temperature_max",
              "precipitation_sum", "wind_speed_10m_max"]:
        df2.loc[fut, c] = df2.loc[fut, c] + 25
    f1, f2 = make_features(_labelled(df)), make_features(_labelled(df2))
    pd.testing.assert_frame_equal(f1[f1["date"] <= T].reset_index(drop=True),
                                  f2[f2["date"] <= T].reset_index(drop=True))


def test_target_is_the_future_flag():
    df = _fixture(1)
    lab = _labelled(df)
    t = add_targets(make_features(lab), lab, [1, 2, 3])
    lab = lab.sort_values(["district_id", "date"]).reset_index(drop=True)
    for h in (1, 2, 3):
        exp = lab["heat"].shift(-h)
        assert t[f"heat_h{h}"].fillna(-1).tolist() == exp.fillna(-1).tolist()


def test_split_is_ordered_and_purged():
    """Leakage control 3: no row's target day reaches into a later split."""
    gold = build_gold_heat(_fixture(), TH, SP)
    mh = max(SP["horizons_days"])
    tr = gold[gold["split"] == "train"]
    va = gold[gold["split"] == "valid"]
    te = gold[gold["split"] == "test"]
    assert tr["date"].max() + pd.Timedelta(days=mh) <= pd.Timestamp(SP["train_end"])
    assert va["date"].max() + pd.Timedelta(days=mh) <= pd.Timestamp(SP["valid_end"])
    assert tr["date"].max() < va["date"].min() < va["date"].max() < te["date"].min()
    assert set(gold["split"]) <= {"train", "valid", "test", "purged"}
    assert (gold["split"] == "purged").sum() > 0


def test_assign_split_boundaries():
    """Horizon 3: day t is purged if t+3 passes the split end (train_end 2022-12-31, valid_end 2023-12-31)."""
    d = pd.Series(pd.to_datetime(["2022-12-28", "2022-12-29", "2023-01-01", "2023-12-28",
                                  "2023-12-29", "2024-01-01"]))
    assert assign_split(d, SP).tolist() == ["train", "purged", "valid", "valid", "purged", "test"]


@pytest.mark.skipif(not REAL, reason="real Silver climate table not present")
def test_real_causal_and_has_positives_in_every_split():
    df = pd.read_parquet(REAL)
    _feat_equal_before(df[df["district_id"].isin(sorted(df["district_id"].unique())[:5])], pd.Timestamp("2023-06-30"))
    gold = build_gold_heat(df, TH, SP)
    pos = gold[gold["split"].isin(["train", "valid", "test"])].groupby("split")["heat_h1"].sum()
    assert (pos > 0).all(), pos.to_dict()
    assert gold.isna().sum().sum() == 0
    assert gold.duplicated(["district_id", "date"]).sum() == 0
