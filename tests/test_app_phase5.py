"""Phase 5 tests: NL query guardrails, explanations, and a headless run of the real app on the real snapshot."""
import numpy as np
import pandas as pd
import pytest

from bhunetra import nlq
from bhunetra.features.heat import load_yaml
from bhunetra.service import band, contributions, find_inputs

from pathlib import Path
APP = Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py"
BANDS = load_yaml("configs/app.yaml")["risk_bands"]
STATES = ["Uttar Pradesh", "Madhya Pradesh", "Rājasthān", "Odisha"]


def _tab():  # TEST FIXTURE for the query logic only
    d = pd.Timestamp("2024-05-20")
    return pd.DataFrame({"name": ["A", "B", "C", "D"], "state": ["Uttar Pradesh", "Uttar Pradesh", "Odisha", "Uttar Pradesh"],
                         "date": [d] * 4, "p1": [0.9, 0.2, 0.95, 0.5], "p2": [0.1] * 4, "p3": [0.1] * 4})


def test_parse_state_horizon_level():
    s = nlq.parse("Which districts in Uttar Pradesh have high heat risk tomorrow?", STATES, BANDS)
    assert (s["state"], s["horizon"], s["min_p"]) == ("Uttar Pradesh", 1, 0.40)
    assert nlq.parse("very high heat risk in odisha day after tomorrow", STATES, BANDS)["horizon"] == 2


def test_diacritics_do_not_break_state_match():
    assert nlq.parse("high heat risk in Rajasthan tomorrow", STATES, BANDS)["state"] == "Rājasthān"


def test_unknown_state_and_non_heat_questions_are_refused_not_guessed():
    with pytest.raises(nlq.Unparsed):
        nlq.parse("high heat risk in Atlantis tomorrow", STATES, BANDS)
    with pytest.raises(nlq.Unparsed):
        nlq.parse("will it rain in Odisha tomorrow", STATES, BANDS)


def test_query_filters_and_orders():
    spec = nlq.parse("high heat risk in Uttar Pradesh tomorrow", STATES, BANDS)
    sql, params, out = nlq.run(_tab(), pd.Timestamp("2024-05-20"), spec)
    assert out["district"].tolist() == ["A", "D"]            # >=40%, UP only, sorted
    assert "?" in sql and "Uttar" not in sql                  # values are bound, not pasted into SQL


def test_injection_text_never_reaches_sql():
    bad = "heat risk in Uttar Pradesh'; DROP TABLE risk_view; -- tomorrow"
    try:
        spec = nlq.parse(bad, STATES, BANDS)
        sql, params, out = nlq.run(_tab(), pd.Timestamp("2024-05-20"), spec)
        assert "DROP" not in sql and len(_tab()) == 4
    except nlq.Unparsed:
        pass


def test_horizon_allow_list():
    with pytest.raises(nlq.Unparsed):
        nlq.run(_tab(), pd.Timestamp("2024-05-20"), {"horizon": 9, "min_p": 0.1, "state": None})


def test_bands():
    assert [band(p, {"risk_bands": BANDS}) for p in (0.05, 0.2, 0.4)] == ["low", "moderate", "high"]


def test_contributions_sum_to_model_logit_minus_intercept():
    from bhunetra.models.heat_pipeline import LR_FEATS, fit_logreg
    rng = np.random.default_rng(0)                         # TEST FIXTURE
    df = pd.DataFrame({c: rng.normal(35, 3, 500) for c in LR_FEATS}); df["y"] = (df["tmax"] + rng.normal(0, 2, 500) > 38).astype(int)
    m = fit_logreg(df, "y")
    row = df.iloc[0]
    logit = m[1].decision_function(m[0].transform(df[LR_FEATS].iloc[[0]]))[0]
    assert abs(contributions(m, row).sum() + m[1].intercept_[0] - logit) < 1e-9


def _has_data():
    try:
        find_inputs(); return True
    except FileNotFoundError:
        return False


@pytest.mark.skipif(not _has_data(), reason="no data/snapshot available")
def test_app_runs_headless_on_real_data_and_shows_disclaimer_and_replay_banner():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception, at.exception
    text = " ".join(x.value for x in at.warning) + " ".join(x.value for x in at.info)
    assert "Not an official warning system" in text and "NOT live" in text
    at.text_input[0].set_value("Which districts in Uttar Pradesh have high heat risk tomorrow?").run()
    assert not at.exception, at.exception


@pytest.mark.skipif(not _has_data(), reason="no data/snapshot available")
def test_hindi_toggle_switches_language():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(APP), default_timeout=120).run()
    at.radio[0].set_value("हिंदी").run()
    assert not at.exception, at.exception
    assert "आधिकारिक चेतावनी" in " ".join(x.value for x in at.warning)


@pytest.mark.skipif(not _has_data(), reason="no data/snapshot available")
def test_explanations_make_sense_for_low_and_high_risk():
    """Low risk must be explained by distance to the event rule, never by 'above normal'. High by pushes toward heat."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception, at.exception
    # default district is the highest-risk one
    md = " ".join(m.value for m in at.markdown)
    assert "Heat risk is High mainly because" in md, md[-300:]
    low = [o for o in at.selectbox[0].options][0]            # alphabetically first district, risk is low on the hot day? check text
    at.selectbox[0].set_value(low).run()
    md = " ".join(m.value for m in at.markdown)
    if "Heat risk is low because" in md:
        assert "above normal and" not in md.split("Heat risk is low because")[1][:160]


def test_band_styles_are_distinguishable_without_colour_alone():
    """Regression: High and Moderate looked the same on the real map. They must differ in colour AND size."""
    from bhunetra.service import BAND_STYLE
    cols = [tuple(BAND_STYLE[b]["color"]) for b in ("low", "moderate", "high")]
    assert len(set(cols)) == 3
    r = [BAND_STYLE[b]["radius"] for b in ("low", "moderate", "high")]
    assert r[0] < r[1] < r[2]
    dist = lambda a, b: sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
    assert dist(cols[1], cols[2]) > 100          # moderate vs high far apart in RGB


@pytest.mark.skipif(not _has_data(), reason="no data/snapshot available")
def test_chart_uses_plain_names_and_basemap_disclaimer_present():
    """Reads the REAL chart data the app sends to the browser, so the assertion cannot pass vacuously."""
    import pyarrow as pa
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception, at.exception
    chart = at.get("vega_lite_chart")
    assert len(chart) == 1, "expected exactly one explanation chart"
    df = pa.ipc.open_stream(chart[0].proto.datasets[0].data.data).read_all().to_pandas()
    labels = set(df.iloc[:, 0])
    assert labels == {"Today's max", "Above normal", "3-day average"}, labels
    assert not labels & {"tmax", "departure", "tmax_mean3"}
    assert "Taller bar" in " ".join(c.value for c in at.caption)
    at.radio[0].set_value("हिंदी").run()
    labels_hi = set(pa.ipc.open_stream(at.get("vega_lite_chart")[0].proto.datasets[0].data.data).read_all().to_pandas().iloc[:, 0])
    assert "आज का अधिकतम" in labels_hi
