"""TabPFN vs LightGBM on the SAME subsample (fair fight). The pure helpers here are unit-tested.

The TabPFN call itself has NOT been run by the author: it needs GPU + HuggingFace weights
(newer weights require accepting terms on HuggingFace; the licence has a non-commercial clause).
Run it with pipelines/tabpfn_colab.py in Colab.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def subsample_train(train: pd.DataFrame, target: str, max_rows: int, seed: int = 42):
    """Keep ALL positives, fill the rest with random negatives up to max_rows.

    TabPFN has a training-size limit (about 10,000 rows in v2, 50,000 in v2.5 per its docs),
    and we have ~65,000 rows with 0.6% positives. Returns (sample, q) where q = share of negatives kept.
    """
    pos = train[train[target] == 1]
    neg = train[train[target] == 0]
    k = max(0, min(len(neg), max_rows - len(pos)))
    sample = pd.concat([pos, neg.sample(n=k, random_state=seed)]).sample(frac=1, random_state=seed)
    return sample, (k / len(neg) if len(neg) else 1.0)


def prior_correct(p: np.ndarray, q: float) -> np.ndarray:
    """Undo negative-undersampling: true odds = sample odds * q  (positives were kept with probability 1)."""
    p = np.clip(np.asarray(p, float), 1e-9, 1 - 1e-9)
    odds = p / (1 - p) * q
    return odds / (1 + odds)
