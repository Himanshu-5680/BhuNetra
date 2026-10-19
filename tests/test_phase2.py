"""Phase 2 tests.

TEST FIXTURES below are tiny hand-written payloads that copy the *shape* of the documented
API responses. They exist only to test our code paths. They are never shown in the app.
Real-data check: see `bhunetra ingest` (needs internet) and reports/phase2_live_check.md.
"""
import json

import pandas as pd
import pandera.pandas as pa
import pytest
import responses

from bhunetra.clean.silver import SCHEMAS, parse_open_meteo, parse_usgs, write_silver
from bhunetra.ingest.boundaries import ingest_boundaries
from bhunetra.net import DataUnavailable, fetch_to_bronze

URL = "https://api.open-meteo.com/v1/forecast"
VARS = ["temperature_2m", "relative_humidity_2m", "apparent_temperature", "precipitation", "wind_speed_10m"]


def _block(temp=30.0):  # TEST FIXTURE
    t = ["2026-01-01T00:00", "2026-01-01T01:00"]
    return {"hourly": {"time": t, **{v: [temp, temp] for v in VARS}}}


@responses.activate
def test_fetch_saves_raw_and_provenance(tmp_path):
    responses.add(responses.GET, URL, json=_block(), status=200)
    f = fetch_to_bronze("t", URL, params={"a": 1, "api_key": "SECRET"}, bronze_dir=tmp_path)
    assert f.path.exists()
    meta = json.loads((f.path.with_suffix(".json.meta.json")).read_text())
    assert len(meta["sha256"]) == 64 and meta["http_status"] == 200
    assert "SECRET" not in json.dumps(meta)          # secrets never stored


@responses.activate
def test_retries_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    responses.add(responses.GET, URL, status=503)
    responses.add(responses.GET, URL, status=429)
    responses.add(responses.GET, URL, json=_block(), status=200)
    f = fetch_to_bronze("t", URL, bronze_dir=tmp_path)
    assert f.meta["http_status"] == 200 and len(responses.calls) == 3


@responses.activate
def test_gives_up_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    responses.add(responses.GET, URL, status=503)
    with pytest.raises(DataUnavailable):
        fetch_to_bronze("t", URL, retries=2, bronze_dir=tmp_path)


@responses.activate
def test_client_error_not_retried(tmp_path):
    responses.add(responses.GET, URL, status=400)
    with pytest.raises(DataUnavailable):
        fetch_to_bronze("t", URL, bronze_dir=tmp_path)
    assert len(responses.calls) == 1


@responses.activate
def test_lfs_pointer_detected(tmp_path):
    from bhunetra.ingest import boundaries as b
    responses.add(responses.GET, b.URL, body="version https://git-lfs.github.com/spec/v1\noid x\n")
    with pytest.raises(RuntimeError, match="LFS"):
        ingest_boundaries(bronze_dir=tmp_path)


def _silver(tmp_path, blocks, ids):
    p = tmp_path / "x.json"
    p.write_text(json.dumps(blocks))
    p.with_suffix(".json.meta.json").write_text(json.dumps(
        {"source": "open_meteo_forecast", "fetched_at_utc": "2026-01-01T000000Z", "sha256": "a" * 64}))
    return parse_open_meteo(p, ids, VARS)


def test_parse_and_validate_ok(tmp_path):
    df = _silver(tmp_path, [_block(30), _block(35)], ["D1", "D2"])
    assert len(df) == 4 and set(df.district_id) == {"D1", "D2"}
    out = write_silver(df, SCHEMAS["weather"], "weather", tmp_path)
    assert len(pd.read_parquet(out)) == 4


def test_misaligned_districts_fail_loudly(tmp_path):
    with pytest.raises(ValueError, match="blocks"):
        _silver(tmp_path, [_block()], ["D1", "D2"])


def test_impossible_temperature_rejected(tmp_path):
    df = _silver(tmp_path, [_block(999)], ["D1"])
    with pytest.raises(pa.errors.SchemaErrors):
        write_silver(df, SCHEMAS["weather"], "weather", tmp_path)


def test_duplicate_rows_rejected(tmp_path):
    df = _silver(tmp_path, [_block()], ["D1"])
    with pytest.raises(pa.errors.SchemaErrors):
        write_silver(pd.concat([df, df], ignore_index=True), SCHEMAS["weather"], "weather", tmp_path)


def test_missing_variable_fails_loudly(tmp_path):
    b = _block(); del b["hourly"]["precipitation"]
    with pytest.raises(KeyError):
        _silver(tmp_path, [b], ["D1"])


def test_usgs_parse(tmp_path):
    gj = {"features": [{"id": "us1", "properties": {"time": 1767225600000, "mag": 4.1, "place": "x"},
                        "geometry": {"coordinates": [77.0, 28.0, 10.0]}}]}  # TEST FIXTURE
    p = tmp_path / "q.json"; p.write_text(json.dumps(gj))
    p.with_suffix(".json.meta.json").write_text(json.dumps(
        {"source": "usgs_earthquakes", "fetched_at_utc": "x", "sha256": "b" * 64}))
    df = parse_usgs(p)
    write_silver(df, SCHEMAS["quakes"], "quakes", tmp_path)
    assert df.loc[0, "magnitude"] == 4.1


def test_cli_ingest_without_network_fails_honestly(tmp_path, monkeypatch, capsys):
    """Offline case: must print DATA UNAVAILABLE and exit non-zero, never write fake data."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("time.sleep", lambda s: None)
    import requests
    def boom(*a, **k): raise requests.ConnectionError("no network")
    monkeypatch.setattr(requests.Session, "get", boom)
    from bhunetra.cli import main
    assert main(["ingest", "quakes"]) == 2
    assert "DATA UNAVAILABLE" in capsys.readouterr().err
    assert not list((tmp_path / "data" / "bronze").rglob("*.json"))
