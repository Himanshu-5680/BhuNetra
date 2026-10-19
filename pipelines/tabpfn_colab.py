"""Run TabPFN on the heat task (Colab with GPU). NOT RUN BY THE AUTHOR YET: no scores are claimed.

Setup in Colab:   !pip install -e ".[ml]" tabpfn
Weights come from HuggingFace automatically; if the model page asks you to accept terms, do that
and set HF_TOKEN. Check the licence (non-commercial clause) before any commercial use.
Usage:            !python pipelines/tabpfn_colab.py --max-rows 10000
Writes reports/tabpfn_results.csv with TabPFN and LightGBM trained on the SAME subsample.
"""
import argparse
import warnings

import pandas as pd

from bhunetra.models.heat_pipeline import feature_cols, fit_clf
from bhunetra.models.metrics import best_f1_threshold, scores
from bhunetra.models.tabpfn_eval import prior_correct, subsample_train

warnings.filterwarnings("ignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rows", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    from tabpfn import TabPFNClassifier      # imported here so the rest of the repo works without it

    g = pd.read_parquet("data/gold/heat_features.parquet")
    feats = feature_cols(g)
    tr, va, te = (g[g.split == s] for s in ("train", "valid", "test"))
    rows = []
    for h in (1, 2, 3):
        t = f"heat_h{h}"
        samp, q = subsample_train(tr, t, a.max_rows, a.seed)
        print(f"h{h}: {len(samp)} rows, {int(samp[t].sum())} positives, negatives kept {q:.1%}")
        tab = TabPFNClassifier(random_state=a.seed).fit(samp[feats], samp[t])
        lgb_m = fit_clf(samp[feats], samp[t], va[feats], va[t], a.seed)
        for name, pv, pt in (
            ("tabpfn", prior_correct(tab.predict_proba(va[feats])[:, 1], q), prior_correct(tab.predict_proba(te[feats])[:, 1], q)),
            ("lightgbm_same_subsample", prior_correct(lgb_m.predict_proba(va[feats])[:, 1], q), prior_correct(lgb_m.predict_proba(te[feats])[:, 1], q)),
        ):
            thr = best_f1_threshold(va[t], pv)
            rows.append({"horizon_days": h, "method": name, "train_rows": len(samp), **scores(te[t], pt, thr, tr[t].mean())})
    out = pd.DataFrame(rows)
    out.to_csv("reports/tabpfn_results.csv", index=False)
    print(out[["horizon_days", "method", "pr_auc", "roc_auc", "brier", "precision", "recall", "f1"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
