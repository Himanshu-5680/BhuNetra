"""Phase 3a tests. Synthetic shapes are TEST FIXTURES (logic only, never shown in the app).
`test_real_*` run on the real geoBoundaries file when present (BHUNETRA_REAL_ADM2 or data/bronze)."""
import glob
import json
import os

import pandas as pd
import pytest
import responses
from shapely.geometry import Point, shape

from bhunetra.clean.silver import SCHEMAS, parse_history, write_silver
from bhunetra.ingest import history
from bhunetra.ingest.districts import assign_states, load_districts, stratified_sample

L = [[[0, 0], [10, 0], [10, 1], [1, 1], [1, 10], [0, 10], [0, 0]]]  # concave: centroid is outside


def _gj(path, feats):
    path.write_text(json.dumps({"features": feats})); return path


def test_point_inside_concave_polygon(tmp_path):
    p = _gj(tmp_path / "a.geojson", [{"properties": {"shapeID": "T1", "shapeName": "L"},
                                      "geometry": {"type": "Polygon", "coordinates": L}}])
    d = load_districts(p)[0]
    assert shape({"type": "Polygon", "coordinates": L}).contains(Point(d["lon"], d["lat"]))


def test_state_assignment_and_unassigned(tmp_path):
    sq = lambda x: {"type": "Polygon", "coordinates": [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]]}
    adm1 = _gj(tmp_path / "s.geojson", [{"properties": {"shapeName": "A"}, "geometry": sq(0)},
                                        {"properties": {"shapeName": "B"}, "geometry": sq(1)}])
    d = pd.DataFrame({"district_id": ["1", "2", "3"], "lon": [0.5, 1.5, 50.0], "lat": [0.5, 0.5, 0.5]})
    out = assign_states(d, adm1)
    assert out.state.iloc[:2].tolist() == ["A", "B"] and pd.isna(out.state.iloc[2])   # outside point left empty, not guessed


def test_stratified_sample_covers_every_state_and_is_deterministic():
    d = pd.DataFrame({"district_id": [str(i) for i in range(40)],
                      "state": ["A"] * 20 + ["B"] * 15 + ["C"] * 5})
    m1, m2 = stratified_sample(d, n_total=6, seed=1), stratified_sample(d, n_total=6, seed=1)
    assert m1.equals(m2) and set(d[m1].state) == {"A", "B", "C"}


def _resp(n_loc):  # TEST FIXTURE shaped like the archive daily response
    blk = {"daily": {"time": ["2024-01-01", "2024-01-02"], **{v: [20.0, 21.0] for v in history.DAILY_VARS}}}
    return [blk] * n_loc


@responses.activate
def test_history_resumes_and_respects_budget(tmp_path):
    pts = pd.DataFrame({"district_id": [f"D{i}" for i in range(20)], "lat": [20.0] * 20, "lon": [77.0] * 20})
    responses.add(responses.GET, history.URL, json=_resp(10))
    r1 = history.ingest_history(pts, 2024, 2024, max_weight=300, pause_s=0, per_minute=None, bronze_dir=tmp_path, log=lambda *_: None)
    assert r1["new"] == 1 and r1["complete"] is False          # budget hit after the first batch of 10
    r2 = history.ingest_history(pts, 2024, 2024, max_weight=9999, pause_s=0, per_minute=None, bronze_dir=tmp_path, log=lambda *_: None)
    assert r2["skipped"] == 1 and r2["new"] == 1 and r2["complete"]   # resumed: no duplicate download


@responses.activate
def test_history_parse_validate_and_reject_bad(tmp_path):
    responses.add(responses.GET, history.URL, json=_resp(2))
    f = history.fetch_to_bronze(history.SOURCE, history.URL, bronze_dir=tmp_path, extra_meta={"district_ids": ["D1", "D2"]})
    df = parse_history(f.path, ["D1", "D2"], history.DAILY_VARS)
    write_silver(df, SCHEMAS["climate"], "c", tmp_path)
    df.loc[0, "temperature_2m_max"] = 99.0
    import pandera.pandas as pa
    with pytest.raises(pa.errors.SchemaErrors):
        write_silver(df, SCHEMAS["climate"], "c", tmp_path)


REAL = os.environ.get("BHUNETRA_REAL_ADM2") or next(iter(glob.glob("data/bronze/geoboundaries_ind_adm2/*.geojson")), None)


@pytest.mark.skipif(not REAL, reason="real ADM2 file not present")
def test_real_all_735_points_inside_their_polygon():
    gj = json.load(open(REAL))
    pts = load_districts(REAL)
    assert len(pts) == len(gj["features"]) >= 700
    bad = [p["district_id"] for p, f in zip(pts, gj["features"])
           if not shape(f["geometry"]).contains(Point(p["lon"], p["lat"]))]
    assert bad == []
    assert len({p["district_id"] for p in pts}) == len(pts)   # ids unique even though names are not


@responses.activate
def test_history_429_waits_then_continues(tmp_path, monkeypatch):
    """Server says 429 once for a whole retry round; we wait and retry the SAME batch."""
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    pts = pd.DataFrame({"district_id": [f"D{i}" for i in range(10)], "lat": [20.0] * 10, "lon": [77.0] * 10})
    for _ in range(5):                       # one full retry round of 429s (retries=4 -> 5 tries)
        responses.add(responses.GET, history.URL, status=429, body="minutely limit exceeded")
    responses.add(responses.GET, history.URL, json=_resp(10))
    r = history.ingest_history(pts, 2024, 2024, rate_wait_s=70, bronze_dir=tmp_path, log=lambda *_: None)
    assert r["complete"] and r["new"] == 1 and 70 in sleeps


@responses.activate
def test_history_gives_up_on_persistent_429_and_keeps_progress(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    pts = pd.DataFrame({"district_id": [f"D{i}" for i in range(10)], "lat": [20.0] * 10, "lon": [77.0] * 10})
    responses.add(responses.GET, history.URL, status=429, body="Daily API request limit exceeded")
    r = history.ingest_history(pts, 2024, 2024, max_rate_waits=1, bronze_dir=tmp_path, log=lambda *_: None)
    assert r["complete"] is False and r["stopped"] == "rate_limit" and "Daily" in r["server_said"]


def test_pacing_math():
    # a 10-district year costs ~261 est. calls; at 400/min that is ~39s between batches
    assert round(history.est_weight(366, 10) / 400 * 60) == 39
