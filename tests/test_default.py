"""The shipped default must be the simple model, and must not see test-year data when fitted."""
import numpy as np
import pandas as pd

from bhunetra.features.heat import load_yaml
from bhunetra.models import default as D
from bhunetra.models.heat_pipeline import LR_FEATS, fit_logreg, lr_proba


def _gold(n=400, seed=0):  # TEST FIXTURE: only checks the wiring, not the science
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    split = np.where(dates <= "2022-12-31", "train", np.where(dates <= "2023-12-31", "valid", "test"))
    df = pd.DataFrame({"district_id": "D0", "date": dates, "split": split, "heat_h1": rng.integers(0, 2, n)})
    for c in LR_FEATS:
        df[c] = rng.normal(35, 3, n)
    return df


def test_default_is_the_simple_model():
    assert D.default_name() == "logreg"
    assert load_yaml("configs/models.yaml")["heat"]["logreg_features"] == LR_FEATS


def test_default_fit_never_uses_test_rows():
    g = _gold()
    m1 = D.fit_default(g, "heat_h1")
    g2 = g.copy()
    g2.loc[g2.split == "test", LR_FEATS] += 100          # change ONLY test-year rows
    m2 = D.fit_default(g2, "heat_h1")
    np.testing.assert_allclose(m1.predict_proba(g[LR_FEATS])[:, 1], m2.predict_proba(g[LR_FEATS])[:, 1])


def test_default_matches_pipeline_logreg_on_same_training_rows():
    g = _gold()
    tv = g[g.split.isin(["train", "valid"])]
    np.testing.assert_allclose(lr_proba(fit_logreg(tv, "heat_h1"), g), D.predict_default(D.fit_default(g, "heat_h1"), g))
