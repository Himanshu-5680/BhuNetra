"""The default heat model used by the app/API. Reads configs/models.yaml, so the choice lives in one place."""
from __future__ import annotations

import pandas as pd

from bhunetra.features.heat import load_yaml
from bhunetra.models.heat_pipeline import fit_logreg, lr_proba


def default_name() -> str:
    return load_yaml("configs/models.yaml")["heat"]["default_model"]


def fit_default(gold: pd.DataFrame, target: str):
    """Fit the configured default on train+valid (data up to 2023), as the config says."""
    cfg = load_yaml("configs/models.yaml")["heat"]
    if cfg["refit_on"] != "train_plus_valid":
        raise ValueError(f"unknown refit_on: {cfg['refit_on']}")
    tv = gold[gold["split"].isin(["train", "valid"])]
    if default_name() != "logreg":
        raise NotImplementedError("only logreg is wired as default so far")
    return fit_logreg(tv, target)


def predict_default(model, df: pd.DataFrame):
    return lr_proba(model, df)
