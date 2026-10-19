"""Heat risk models + honest evaluation. Run via `bhunetra train`.

Three validation designs (all time-ordered, nothing shuffled):
  time_split    train 2020-22 / valid 2023 / test 2024, same districts.
  unseen_state  as above, but test districts belong to STATES the model never saw (strictest).
  rolling       expanding window, test years 2022, 2023, 2024; labels/normal rebuilt per fold.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from bhunetra.features.heat import build_gold_heat, compute_normal, day_of_year_365, load_yaml
from bhunetra.models import baselines as B
from bhunetra.models.metrics import best_f1_threshold, calibration_table, cqr_interval, scores

PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=15, min_child_samples=50,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, reg_lambda=1.0,
              verbose=-1, n_jobs=1)
NOT_FEATURES = {"district_id", "date", "split", "state"}
# Simple model that LightGBM must beat. On real data (only ~400 training positives) it won, so it stays in.
LR_FEATS = ["tmax", "departure", "tmax_mean3"]


def fit_logreg(tr: pd.DataFrame, target: str):
    """3-feature logistic regression with standardised inputs: the 'simplest model that wins' candidate."""
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(tr[LR_FEATS], tr[target])


def lr_proba(model, df: pd.DataFrame) -> np.ndarray:
    return model.predict_proba(df[LR_FEATS])[:, 1]


def feature_cols(g: pd.DataFrame) -> list[str]:
    return [c for c in g.columns if c not in NOT_FEATURES and not c.startswith("heat_h")]


def fit_clf(Xtr, ytr, Xva, yva, seed: int, n_estimators: int = 800, early: bool = True):
    m = lgb.LGBMClassifier(**PARAMS, n_estimators=n_estimators, random_state=seed)
    if not early:
        return m.fit(Xtr, ytr)
    metric = "average_precision" if yva.sum() > 0 else "binary_logloss"   # AP is undefined with no positives
    return m.fit(Xtr, ytr, eval_set=[(Xva, yva)], eval_metric=metric,
                 callbacks=[lgb.early_stopping(50, verbose=False)])


def _row(design, h, method, subset, thr, y, p, ref, **extra):
    return {"design": design, "horizon_days": h, "method": method, "subset": subset,
            "threshold": thr, **scores(y, p, thr, ref), **extra}


def _subsets(df: pd.DataFrame) -> dict[str, np.ndarray]:
    m = df["date"].dt.month
    return {"all": np.ones(len(df), bool), "onset": (df["heat_today"] == 0).to_numpy(),
            "apr_jun": m.isin([4, 5, 6]).to_numpy(), "other_months": (~m.isin([4, 5, 6])).to_numpy()}


# ----------------------------------------------------------------------------------------------
def time_split(gold, feats, history, seeds, rows, keep):
    tr, va, te = (gold[gold.split == s] for s in ("train", "valid", "test"))
    for h in (1, 2, 3):
        t = f"heat_h{h}"
        ref = tr[t].mean()
        clim = B.climatology_fit(tr, h, by_district=True)
        methods = {"persistence": (B.persistence(va), B.persistence(te)),
                   "climatology": (B.climatology_predict(clim, va), B.climatology_predict(clim, te)),
                   "seasonal_naive": (B.seasonal_naive(va, history, h), B.seasonal_naive(te, history, h))}
        lr = fit_logreg(tr, t)
        methods["logreg"] = (lr_proba(lr, va), lr_proba(lr, te))
        lg_va, lg_te, best_it = [], [], []
        for sd in seeds:
            m = fit_clf(tr[feats], tr[t], va[feats], va[t], sd)
            best_it.append(m.best_iteration_ or m.n_estimators)
            lg_va.append(m.predict_proba(va[feats])[:, 1]); lg_te.append(m.predict_proba(te[feats])[:, 1])
            if sd == seeds[0]:
                keep[("model", h)] = m
        for name, (pv, pt) in methods.items():
            thr = best_f1_threshold(va[t], pv)
            for sub, mask in _subsets(te).items():
                rows.append(_row("time_split", h, name, sub, thr, te[t][mask], pt[mask], ref))
        for i, sd in enumerate(seeds):
            thr = best_f1_threshold(va[t], lg_va[i])
            for sub, mask in _subsets(te).items():
                rows.append(_row("time_split", h, "lightgbm", sub, thr, te[t][mask], lg_te[i][mask], ref, seed=sd))
        # calibrated variant (isotonic fitted on VALID only), first seed
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(lg_va[0], va[t])
        pc = iso.predict(lg_te[0])
        thr = best_f1_threshold(va[t], iso.predict(lg_va[0]))
        rows.append(_row("time_split", h, "lightgbm_calibrated", "all", thr, te[t], pc, ref, seed=seeds[0]))
        keep[("preds", h)] = dict(y=te[t].to_numpy(), lgb=lg_te[0], lgb_cal=pc, pers=methods["persistence"][1],
                                  clim=methods["climatology"][1], lr=methods["logreg"][1])
        keep[("best_it", h)] = int(np.median(best_it))
        keep[("test", h)] = te


def unseen_state(gold, feats, states, rows, n_folds=5, seed=42):
    rng = np.random.default_rng(seed)
    st = np.array(sorted(s for s in gold["state"].dropna().unique()))
    rng.shuffle(st)
    folds = [set(st[i::n_folds]) for i in range(n_folds)]
    fold_rows = []
    for h in (1, 2, 3):
        t = f"heat_h{h}"
        P = {"lightgbm": [], "logreg": [], "persistence": [], "climatology_pooled": []}
        Y, T, V = [], [], []
        for k, held in enumerate(folds):
            other = ~gold["state"].isin(held)
            tr = gold[(gold.split == "train") & other]
            va = gold[(gold.split == "valid") & other]
            te = gold[(gold.split == "test") & gold["state"].isin(held)]
            if te.empty:
                continue
            assert not (set(tr["state"].dropna()) & set(te["state"].dropna())), "state leak between train and test"
            m = fit_clf(tr[feats], tr[t], va[feats], va[t], seed)
            pv, pt = m.predict_proba(va[feats])[:, 1], m.predict_proba(te[feats])[:, 1]
            cl = B.climatology_fit(tr, h, by_district=False)
            thr_l = best_f1_threshold(va[t], pv)
            thr_c = best_f1_threshold(va[t], B.climatology_predict(cl, va))
            thr_p = best_f1_threshold(va[t], B.persistence(va))
            lr = fit_logreg(tr, t)
            P["logreg"].append((te, lr_proba(lr, te), best_f1_threshold(va[t], lr_proba(lr, va))))
            P["lightgbm"].append((te, pt, thr_l)); P["persistence"].append((te, B.persistence(te), thr_p))
            P["climatology_pooled"].append((te, B.climatology_predict(cl, te), thr_c))
            fold_rows.append({"horizon_days": h, "fold": k, "held_out_states": len(held), "test_positives": int(te[t].sum()),
                              "pr_auc_lightgbm": scores(te[t], pt, thr_l)["pr_auc"],
                              "pr_auc_persistence": scores(te[t], B.persistence(te), thr_p)["pr_auc"],
                              "pr_auc_climatology_pooled": scores(te[t], B.climatology_predict(cl, te), thr_c)["pr_auc"]})
        ref = gold[gold.split == "train"][t].mean()
        for name, parts in P.items():
            te_all = pd.concat([p[0] for p in parts]); p_all = np.concatenate([p[1] for p in parts])
            thr = float(np.mean([p[2] for p in parts]))     # mean of per-fold VALID thresholds
            for sub, mask in _subsets(te_all).items():
                rows.append(_row("unseen_state", h, name, sub, thr, te_all[t][mask], p_all[mask], ref))
    return pd.DataFrame(fold_rows)


def rolling(clim, th, feats_n_est, seed, rows):
    for Y in (2022, 2023, 2024):
        sp = {"train_end": f"{Y-1}-12-31", "valid_end": f"{Y}-12-31", "horizons_days": [1, 2, 3]}
        g = build_gold_heat(clim, th, sp)           # normal + labels rebuilt using ONLY years before Y
        f = feature_cols(g)
        tr, te = g[g.split == "train"], g[g.split == "valid"]   # 'valid' slot = the test year of this fold
        for h in (1, 2, 3):
            t = f"heat_h{h}"
            m = fit_clf(tr[f], tr[t], None, None, seed, n_estimators=feats_n_est[h], early=False)
            pt = m.predict_proba(te[f])[:, 1]
            cl = B.climatology_fit(tr, h, by_district=True)
            ref = tr[t].mean()
            lr = fit_logreg(tr, t)
            for name, p in (("lightgbm", pt), ("logreg", lr_proba(lr, te)), ("persistence", B.persistence(te)),
                            ("climatology", B.climatology_predict(cl, te))):
                # No threshold-dependent metrics here: there is no separate valid year to pick a threshold fairly.
                rows.append(_row("rolling", h, name, "all", np.nan, te[t], p, ref, test_year=Y,
                                 train_positives=int(tr[t].sum())))


def uncertainty(gold, clim, feats, seed, train_end, alpha=0.2):
    """Tmax(t+h) 80% intervals: LightGBM quantiles + conformal widening fitted on VALID."""
    look = clim.set_index(["district_id", "date"])["temperature_2m_max"]
    normal = compute_normal(clim, train_end).set_index(["district_id", "doy"])["tmax_normal"]
    out = []
    qp = dict(PARAMS); qp.pop("objective")
    for h in (1, 2, 3):
        def tgt(df):
            idx = pd.MultiIndex.from_arrays([df["district_id"].to_numpy(), (df["date"] + pd.Timedelta(days=h)).to_numpy()])
            return look.reindex(idx).to_numpy()
        parts = {s: gold[gold.split == s] for s in ("train", "valid", "test")}
        y = {s: tgt(d) for s, d in parts.items()}
        ok = {s: ~np.isnan(y[s]) for s in y}
        X = {s: parts[s][feats][ok[s]] for s in parts}; Y = {s: y[s][ok[s]] for s in y}
        mdl = {a: lgb.LGBMRegressor(objective="quantile", alpha=a, n_estimators=300, random_state=seed, **qp).fit(X["train"], Y["train"])
               for a in (alpha / 2, 0.5, 1 - alpha / 2)}
        pr = {s: {a: m.predict(X[s]) for a, m in mdl.items()} for s in ("valid", "test")}
        lo_v, hi_v, med_v = pr["valid"][alpha / 2], pr["valid"][1 - alpha / 2], pr["valid"][0.5]
        lo_t, hi_t, med_t = pr["test"][alpha / 2], pr["test"][1 - alpha / 2], pr["test"][0.5]
        clo, chi, q = cqr_interval(lo_v, hi_v, Y["valid"], lo_t, hi_t, alpha)
        te = parts["test"][ok["test"]]
        doy = day_of_year_365(te["date"] + pd.Timedelta(days=h))
        nrm = normal.reindex(pd.MultiIndex.from_arrays([te["district_id"].to_numpy(), doy.to_numpy()])).to_numpy()
        yt = Y["test"]
        out.append({"horizon_days": h, "nominal_coverage": 1 - alpha,
                    "coverage_raw_quantiles": float(np.mean((yt >= lo_t) & (yt <= hi_t))),
                    "coverage_conformal": float(np.mean((yt >= clo) & (yt <= chi))),
                    "coverage_conformal_on_valid_by_construction": float(np.mean((Y["valid"] >= lo_v - q) & (Y["valid"] <= hi_v + q))),
                    "mean_width_raw_C": float(np.mean(hi_t - lo_t)), "mean_width_conformal_C": float(np.mean(chi - clo)),
                    "mae_model_median_C": float(np.mean(np.abs(yt - med_t))),
                    "mae_persistence_C": float(np.mean(np.abs(yt - te["tmax"].to_numpy()))),
                    "mae_climatological_normal_C": float(np.nanmean(np.abs(yt - nrm))),
                    "test_rows": int(len(yt))})
    return pd.DataFrame(out)


def shap_summary(model, X, feats, nmax=3000, seed=0):
    import shap
    Xs = X.sample(min(nmax, len(X)), random_state=seed)
    sv = shap.TreeExplainer(model).shap_values(Xs)
    sv = sv[1] if isinstance(sv, list) else sv
    sv = sv[..., 1] if getattr(sv, "ndim", 2) == 3 else sv
    imp = pd.DataFrame({"feature": feats, "mean_abs_shap": np.abs(sv).mean(0)}).sort_values("mean_abs_shap", ascending=False)
    return imp, Xs, sv


def run(data_dir="data", out_dir="reports", seeds=(42, 43, 44, 45, 46), fast=False) -> dict:
    data, out = Path(data_dir), Path(out_dir)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    th, sp = load_yaml("configs/thresholds.yaml"), load_yaml("configs/split.yaml")
    gold = pd.read_parquet(data / "gold" / "heat_features.parquet")
    clim = pd.read_parquet(data / "silver" / "climate_daily.parquet")
    dist = pd.read_parquet(data / "silver" / "districts.parquet")[["district_id", "state"]]
    gold = gold.merge(dist, on="district_id", how="left")
    feats = feature_cols(gold)
    history = gold[["district_id", "date", "heat_today"]]
    if fast:
        seeds = seeds[:1]
    rows, keep = [], {}
    time_split(gold, feats, history, list(seeds), rows, keep)
    fold_df = unseen_state(gold, feats, dist, rows)
    if not fast:
        rolling(clim, th, {h: keep[("best_it", h)] for h in (1, 2, 3)}, seeds[0], rows)
    unc = uncertainty(gold, clim, feats, seeds[0], sp["train_end"])
    imp, Xs, sv = shap_summary(keep[("model", 1)], keep[("test", 1)][feats], feats)
    res = pd.DataFrame(rows)
    res.to_csv(out / "heat_model_results_long.csv", index=False)
    fold_df.to_csv(out / "heat_unseen_state_folds.csv", index=False)
    unc.to_csv(out / "heat_uncertainty.csv", index=False)
    imp.to_csv(out / "heat_shap_importance_h1.csv", index=False)
    calibration_table(keep[("preds", 1)]["y"], keep[("preds", 1)]["lgb"]).to_csv(out / "heat_calibration_h1_raw.csv", index=False)
    calibration_table(keep[("preds", 1)]["y"], keep[("preds", 1)]["lgb_cal"]).to_csv(out / "heat_calibration_h1_calibrated.csv", index=False)
    meta = {"created_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0], "platform": platform.platform(),
            "lightgbm": lgb.__version__, "numpy": np.__version__, "pandas": pd.__version__, "seeds": list(seeds), "params": PARAMS,
            "features": feats, "gold_sha256": hashlib.sha256((data / "gold" / "heat_features.parquet").read_bytes()).hexdigest(),
            "rows": {s: int((gold.split == s).sum()) for s in gold.split.unique()}, "fast_mode": fast,
            "tabpfn": "not run (needs HuggingFace weights + GPU; see pipelines/tabpfn_colab.py)"}
    (out / "heat_run_metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    make_figures(keep, out / "figures")
    (out / "heat_results.md").write_text(render_results_md(res, fold_df, unc, imp, meta))
    keep["results"], keep["unc"], keep["folds"], keep["imp"], keep["shap"] = res, unc, fold_df, imp, (Xs, sv)
    return keep


def make_figures(keep, figdir: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import precision_recall_curve
    P = keep[("preds", 1)]
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    for name, p in (("LightGBM", P["lgb"]), ("logistic (3 features)", P["lr"]), ("persistence", P["pers"]), ("climatology", P["clim"])):
        pr, rc, _ = precision_recall_curve(P["y"], p)
        ax[0].plot(rc, pr, label=name)
    ax[0].set(xlabel="recall", ylabel="precision", title="Heat, 1 day ahead, test 2024 (PR curve)"); ax[0].legend()
    for name, p in (("LightGBM raw", P["lgb"]), ("LightGBM isotonic (fit on 2023)", P["lgb_cal"]), ("logistic", P["lr"])):
        t = calibration_table(P["y"], p)
        ax[1].plot(t["mean_pred"], t["frac_pos"], "o-", label=name)
    ax[1].plot([0, 1], [0, 1], "k--", lw=0.8); ax[1].legend()
    ax[1].set(xlabel="predicted probability", ylabel="observed frequency", title="Reliability, test 2024")
    fig.tight_layout(); fig.savefig(figdir / "heat_h1_pr_and_calibration.png", dpi=130); plt.close(fig)


def _cmp(a: float, b: float, margin: float, higher_better: bool = True) -> str:
    """beats / ties / does NOT beat. Differences smaller than `margin` are called ties (seed noise is about 0.02)."""
    if abs(a - b) < margin:
        return "is about equal to"
    return "beats" if (a > b) == higher_better else "does NOT beat"


def honest_flags(res: pd.DataFrame) -> list[str]:
    """Plain sentences computed from the numbers, so weaknesses cannot be forgotten in the README."""
    out = []
    ts = res[(res.design == "time_split") & (res.subset == "all")]
    for h in (1, 2, 3):
        x = ts[ts.horizon_days == h].groupby("method")[["pr_auc", "f1", "brier"]].mean()
        l, p, g3 = x.loc["lightgbm"], x.loc["persistence"], x.loc["logreg"]
        out.append(f"{h}-day: LightGBM {_cmp(l.pr_auc, p.pr_auc, 0.02)} persistence on PR-AUC ({l.pr_auc:.3f} vs {p.pr_auc:.3f}); "
                   f"{_cmp(l.f1, p.f1, 0.02)} it on F1 ({l.f1:.3f} vs {p.f1:.3f}); "
                   f"{_cmp(l.brier, p.brier, 0.001, higher_better=False)} it on Brier ({l.brier:.3f} vs {p.brier:.3f}, lower is better). "
                   "(ties = difference below 0.02 PR-AUC/F1 or 0.001 Brier)")
        out.append(f"{h}-day: LightGBM {_cmp(l.pr_auc, g3.pr_auc, 0.02)} the 3-feature logistic regression on PR-AUC "
                   f"({l.pr_auc:.3f} vs {g3.pr_auc:.3f}). If it does NOT beat it, the simpler model should be the one we ship.")
    on = res[(res.design == "time_split") & (res.subset == "onset") & (res.method == "lightgbm")].groupby("horizon_days")["recall"].mean()
    out.append("Onset days (no heat today, heat later): LightGBM recall at the chosen threshold is "
               + ", ".join(f"{v:.0%} ({h}-day)" for h, v in on.items()) + "; persistence catches 0% by construction.")
    return out


def render_results_md(res, folds, unc, imp, meta) -> str:
    def tab(df): return df.to_markdown(index=False)
    r = res.copy()
    ts = r[(r.design == "time_split") & (r.subset == "all")]
    a = ts.groupby(["horizon_days", "method"]).agg(pr_auc=("pr_auc", "mean"), pr_auc_sd=("pr_auc", "std"), roc_auc=("roc_auc", "mean"),
                                                    brier=("brier", "mean"), precision=("precision", "mean"), recall=("recall", "mean"),
                                                    f1=("f1", "mean"), test_positives=("positives", "first")).round(3).reset_index()
    u = r[(r.design == "unseen_state") & (r.subset == "all")][["horizon_days", "method", "pr_auc", "roc_auc", "brier", "precision", "recall", "f1", "positives"]].round(3)
    o = r[(r.design == "time_split") & (r.subset == "onset") & r.method.isin(["persistence", "climatology", "lightgbm", "logreg"])]
    o = o.groupby(["horizon_days", "method"]).agg(positives=("positives", "first"), pr_auc=("pr_auc", "mean"), precision=("precision", "mean"), recall=("recall", "mean")).round(3).reset_index()
    has_roll = "test_year" in r.columns and (r.design == "rolling").any()
    ro = (r[r.design == "rolling"][["horizon_days", "test_year", "method", "train_positives", "positives", "pr_auc", "roc_auc", "brier"]].round(3)
          if has_roll else pd.DataFrame())
    L = ["# Heat model results (auto-generated by `bhunetra train`; do not edit by hand)", "",
         f"Run: {meta['created_utc']} | gold sha256 `{meta['gold_sha256'][:12]}` | seeds {meta['seeds']} | fast_mode={meta['fast_mode']}", "",
         "## Honest flags (computed from the numbers below)", *[f"- {x}" for x in honest_flags(r)], "",
         "## A. Time split (train 2020-22, valid 2023, test 2024; mean over seeds for lightgbm)", tab(a), "",
         "Climatology and seasonal_naive ignore today's weather, so their scores are the same at every horizon.", "",
         "## B. Unseen states (model never saw the test states; train 2020-22, test 2024)", tab(u), "",
         "Per-fold PR-AUC, 1 day ahead:", tab(folds[folds.horizon_days == 1].round(3)), "",
         "## C. Onset days only (no heat today)", tab(o), "",
         "## D. Rolling origin (labels/normal rebuilt per fold; threshold-free metrics only)", tab(ro) if has_roll else "not run (fast mode)", "",
         "## E. Uncertainty, Tmax 80% intervals (test 2024)", tab(unc.round(3)), "",
         "## F. SHAP importance, 1 day ahead (mean |SHAP|, model log-odds)", tab(imp.head(10).round(4)), ""]
    return "\n".join(L)
