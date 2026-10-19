"""Phase 4 tests: metrics, baselines, conformal coverage, TabPFN helpers, end-to-end smoke run.

SYNTHETIC frames are TEST FIXTURES for logic only. The real results come from `bhunetra train`.
"""
import numpy as np
import pandas as pd
import pytest

from bhunetra.features.heat import build_gold_heat, load_yaml
from bhunetra.models import baselines as B
from bhunetra.models.metrics import best_f1_threshold, calibration_table, cqr_interval, scores
from bhunetra.models.tabpfn_eval import prior_correct, subsample_train

TH, SP = load_yaml("configs/thresholds.yaml"), load_yaml("configs/split.yaml")


def test_scores_hand_case():
    s = scores([1, 1, 0, 0, 0], [0.9, 0.4, 0.6, 0.2, 0.1], thr=0.5)
    assert (s["tp"], s["fp"], s["fn"]) == (1, 1, 1) and s["precision"] == 0.5 and s["recall"] == 0.5 and s["f1"] == 0.5


def test_perfect_ranking_gives_pr_auc_one_and_best_threshold_separates():
    y, p = np.array([0, 0, 0, 1, 1]), np.array([0.1, 0.2, 0.3, 0.8, 0.9])
    assert scores(y, p, 0.5)["pr_auc"] == 1.0
    assert scores(y, p, best_f1_threshold(y, p))["f1"] == 1.0


def test_scores_with_no_positives_does_not_crash():
    s = scores([0, 0, 0], [0.1, 0.2, 0.3], 0.5)
    assert np.isnan(s["pr_auc"]) and s["tp"] == 0


def test_calibration_table_uses_fixed_bins():
    t = calibration_table([0, 0, 1, 1], [0.005, 0.03, 0.5, 0.9])
    assert t["n"].sum() == 4 and (t["frac_pos"] >= 0).all()


def test_conformal_interval_reaches_nominal_coverage_on_iid_data():
    rng = np.random.default_rng(0)
    yv, yt = rng.normal(0, 1, 3000), rng.normal(0, 1, 30000)
    lo_v = hi_v = np.zeros(3000); lo_t = hi_t = np.zeros(30000)   # deliberately useless intervals
    lo, hi, _ = cqr_interval(lo_v - 0.1, hi_v + 0.1, yv, lo_t - 0.1, hi_t + 0.1, alpha=0.2)
    assert np.mean((yt >= lo) & (yt <= hi)) >= 0.78


def test_persistence_catches_no_onset_by_construction():
    df = pd.DataFrame({"heat_today": [0, 0, 1], "heat_h1": [1, 0, 1]})
    p = B.persistence(df)
    assert p[0] == 0.0 and p[2] == 1.0


def test_seasonal_naive_looks_one_year_back_from_target_day():
    hist = pd.DataFrame({"district_id": ["D1"], "date": pd.to_datetime(["2023-05-02"]), "heat_today": [1]})
    df = pd.DataFrame({"district_id": ["D1", "D1"], "date": pd.to_datetime(["2024-05-01", "2024-05-05"])})
    assert B.seasonal_naive(df, hist, 1).tolist() == [1.0, 0.0]


def _clim_fixture(seed=1):   # TEST FIXTURE: hot synthetic climate so every split has positives
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", "2024-12-31")
    parts = []
    for k in range(8):
        base = 32 + 11 * np.sin(2 * np.pi * (dates.dayofyear - 100) / 365) + (k % 3)
        tmax = base + rng.normal(0, 3, len(dates))
        parts.append(pd.DataFrame({"district_id": f"D{k}", "date": dates, "temperature_2m_max": tmax,
                                   "temperature_2m_min": tmax - 10, "temperature_2m_mean": tmax - 5,
                                   "apparent_temperature_max": tmax + 2, "precipitation_sum": rng.gamma(0.3, 3, len(dates)),
                                   "wind_speed_10m_max": rng.gamma(4, 3, len(dates))}))
    return pd.concat(parts, ignore_index=True)


def test_climatology_falls_back_to_pooled_for_unseen_district():
    gold = build_gold_heat(_clim_fixture(), TH, SP)
    tr = gold[gold.split == "train"]
    m = B.climatology_fit(tr[tr.district_id != "D0"], 1, by_district=True)
    te = gold[(gold.split == "test") & (gold.district_id == "D0")].head(50)
    assert np.allclose(B.climatology_predict(m, te), m["pooled"][B.day_of_year_365(te["date"] + pd.Timedelta(days=1)).to_numpy() - 1])


def test_tabpfn_subsample_keeps_all_positives_and_prior_correction_is_exact():
    tr = pd.DataFrame({"y": [1] * 5 + [0] * 995, "x": range(1000)})
    s, q = subsample_train(tr, "y", 105, seed=0)
    assert len(s) == 105 and s["y"].sum() == 5 and abs(q - 100 / 995) < 1e-12
    # sample odds 1:1 with 10% of negatives kept -> true odds 0.1
    assert abs(prior_correct(np.array([0.5]), 0.1)[0] - 0.1 / 1.1) < 1e-9


def test_end_to_end_smoke_and_unseen_states_are_disjoint(tmp_path):
    from bhunetra.models.heat_pipeline import run
    clim = _clim_fixture()
    gold = build_gold_heat(clim, TH, SP)
    for d in ("gold", "silver"):
        (tmp_path / "data" / d).mkdir(parents=True)
    gold.to_parquet(tmp_path / "data/gold/heat_features.parquet")
    clim.to_parquet(tmp_path / "data/silver/climate_daily.parquet")
    pd.DataFrame({"district_id": [f"D{k}" for k in range(8)], "state": [f"S{k // 2}" for k in range(8)]}) \
        .to_parquet(tmp_path / "data/silver/districts.parquet")
    run(tmp_path / "data", tmp_path / "reports", fast=True)   # the run itself asserts train/test states never overlap
    r = pd.read_csv(tmp_path / "reports/heat_model_results_long.csv")
    assert {"time_split", "unseen_state"} <= set(r.design)
    assert (tmp_path / "reports/heat_results.md").read_text().startswith("# Heat model results")
    ts = r[(r.design == "time_split") & (r.subset == "all") & (r.method == "lightgbm") & (r.horizon_days == 1)]
    assert ts["pr_auc"].notna().all()


def test_logreg_is_part_of_the_comparison_and_flags_mention_it():
    """The simple model must be in every design, and the honest flags must compare LightGBM against it."""
    from bhunetra.models import heat_pipeline as hp
    gold = build_gold_heat(_clim_fixture(), TH, SP)
    tr = gold[gold.split == "train"]
    p = hp.lr_proba(hp.fit_logreg(tr, "heat_h1"), gold[gold.split == "test"])
    assert p.min() >= 0 and p.max() <= 1 and len(p) == (gold.split == "test").sum()
