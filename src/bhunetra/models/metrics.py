"""Metrics for rare-event forecasting. Accuracy is deliberately NOT reported (always saying 'no heat' scores ~97%)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, brier_score_loss, precision_recall_curve,
                             roc_auc_score)


def best_f1_threshold(y, p) -> float:
    """Threshold that maximises F1. Must be chosen on VALID data, never on the test set."""
    y, p = np.asarray(y).astype(int), np.asarray(p, float)
    if y.sum() == 0:
        return 0.5
    pr, rc, th = precision_recall_curve(y, p)
    f1 = 2 * pr * rc / np.clip(pr + rc, 1e-12, None)
    return float(th[int(np.nanargmax(f1[:-1]))]) if len(th) else 0.5


def scores(y, p, thr: float, ref_rate: float | None = None) -> dict:
    """PR-AUC, ROC-AUC, Brier (+ skill vs a constant `ref_rate`), and precision/recall/F1 at `thr`."""
    y, p = np.asarray(y).astype(int), np.asarray(p, float)
    out = {"n": int(len(y)), "positives": int(y.sum()), "prevalence": float(y.mean()) if len(y) else np.nan}
    ok = 0 < y.sum() < len(y)
    out["pr_auc"] = float(average_precision_score(y, p)) if ok else np.nan
    out["roc_auc"] = float(roc_auc_score(y, p)) if ok else np.nan
    pc = np.clip(p, 0, 1)
    out["brier"] = float(brier_score_loss(y, pc)) if len(y) else np.nan
    if ref_rate is not None and len(y):
        ref = float(np.mean((y - ref_rate) ** 2))
        out["brier_skill_vs_constant"] = 1 - out["brier"] / ref if ref > 0 else np.nan
    pred = p >= thr
    tp, fp, fn = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum()), int((~pred & (y == 1)).sum())
    out["precision"] = tp / (tp + fp) if tp + fp else 0.0
    out["recall"] = tp / (tp + fn) if tp + fn else np.nan
    pr_, rc_ = out["precision"], out["recall"]
    out["f1"] = 2 * pr_ * rc_ / (pr_ + rc_) if pr_ + rc_ and not np.isnan(rc_) else 0.0
    out["tp"], out["fp"], out["fn"] = tp, fp, fn
    return out


CAL_EDGES = [0, 0.01, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0001]


def calibration_table(y, p, edges=CAL_EDGES) -> pd.DataFrame:
    """Reliability table with FIXED probability bins (equal-count bins are useless when 97% of rows are ~0)."""
    d = pd.DataFrame({"y": np.asarray(y), "p": np.asarray(p, float)})
    d["bin"] = pd.cut(d["p"], edges, right=False)
    t = d.groupby("bin", observed=True).agg(mean_pred=("p", "mean"), frac_pos=("y", "mean"), n=("y", "size")).reset_index()
    t["bin"] = t["bin"].astype(str)
    return t


def cqr_interval(lo_va, hi_va, y_va, lo_te, hi_te, alpha: float = 0.2):
    """Conformalised quantile regression: widen [lo, hi] so coverage >= 1-alpha on exchangeable data."""
    lo_va, hi_va, y_va = map(np.asarray, (lo_va, hi_va, y_va))
    e = np.maximum(lo_va - y_va, y_va - hi_va)
    n = len(e)
    q = np.quantile(e, min(1.0, np.ceil((n + 1) * (1 - alpha)) / n), method="higher")
    return np.minimum(lo_te, hi_te) - q, np.maximum(lo_te, hi_te) + q, float(q)
