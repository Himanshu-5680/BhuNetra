"""bhunetra command line. Phase 2 commands: ingest, build."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from bhunetra.clean.silver import SCHEMAS, parse_open_meteo, parse_usgs, write_silver
from bhunetra.ingest import boundaries, districts, history, open_meteo, usgs
from bhunetra.net import latest_bronze
import pandas as pd
from bhunetra.net import DataUnavailable


def _bronze_files(source: str, bronze: str = "data/bronze"):
    return sorted(p for p in (Path(bronze) / source).glob("*.json") if not p.name.endswith(".meta.json"))


def _districts_table(limit=None, sample_only=False) -> pd.DataFrame:
    p = Path("data/silver/districts.parquet")
    if not p.exists():
        raise DataUnavailable("Run `bhunetra build-districts` first (needs ADM2 + ADM1 boundaries).")
    d = pd.read_parquet(p)
    if sample_only:
        d = d[d["in_study_sample"]]
    return d.head(limit) if limit else d


def cmd_build_districts(a):
    adm2 = latest_bronze("geoboundaries_ind_adm2", ext="geojson")
    adm1 = latest_bronze("geoboundaries_ind_adm1", ext="geojson")
    d = districts.assign_states(pd.DataFrame(districts.load_districts(adm2)), adm1)
    d["in_study_sample"] = districts.stratified_sample(d, n_total=a.n)
    Path("data/silver").mkdir(parents=True, exist_ok=True)
    d.to_parquet("data/silver/districts.parquet", index=False)
    print(f"{len(d)} districts | states found: {d.state.nunique()} | unassigned: {int(d.state.isna().sum())}"
          f" | study sample: {int(d.in_study_sample.sum())}")
    print(d[d.in_study_sample].groupby("state").size().sort_values().to_string())
    return 0


def cmd_ingest(a):
    try:
        if a.what in ("boundaries", "states"):
            f = boundaries.ingest_boundaries("ADM2" if a.what == "boundaries" else "ADM1")
            print(f"saved {f.path} sha256={f.meta['sha256'][:12]}...")
        elif a.what in ("weather", "air"):
            pts = _districts_table(a.limit, a.sample)
            fn = open_meteo.ingest_forecast if a.what == "weather" else open_meteo.ingest_air_quality
            files = fn(pts)
            print(f"saved {len(files)} files for {len(pts)} districts")
        elif a.what == "history":
            pts = _districts_table(sample_only=True)
            r = history.ingest_history(pts, a.first_year, a.last_year, max_weight=a.budget)
            print(r)
        elif a.what == "quakes":
            end = date.today(); start = end - timedelta(days=a.days)
            f = usgs.ingest_earthquakes(start.isoformat(), end.isoformat())
            print(f"saved {f.path} sha256={f.meta['sha256'][:12]}...")
    except DataUnavailable as e:
        print(f"DATA UNAVAILABLE: {e}", file=sys.stderr)  # honest failure, no fake fill
        return 2
    return 0


def history_parse(p, ids):
    from bhunetra.clean.silver import parse_history
    return parse_history(p, ids, history.DAILY_VARS)


def cmd_build(a):
    n = 0
    for src, name, vars_ in (("open_meteo_forecast", "weather", open_meteo.FORECAST_VARS),
                             ("open_meteo_air", "air", open_meteo.AIR_VARS)):
        import pandas as pd
        frames = []
        for p in _bronze_files(src):
            ids = json.loads(p.with_suffix(".json.meta.json").read_text())["district_ids"]
            frames.append(parse_open_meteo(p, ids, vars_))
        if frames:
            df = pd.concat(frames, ignore_index=True)
            # Same hour fetched twice -> keep the most recent fetch.
            df = df.sort_values("fetched_at_utc").drop_duplicates(["district_id", "time_utc"], keep="last")
            print("silver:", write_silver(df, SCHEMAS[name], name), len(df), "rows"); n += 1
    hist = _bronze_files("open_meteo_history")
    if hist:
        fr = []
        for p in hist:
            ids = json.loads(p.with_suffix(".json.meta.json").read_text())["district_ids"]
            fr.append(history_parse(p, ids))
        df = pd.concat(fr, ignore_index=True).sort_values("fetched_at_utc").drop_duplicates(["district_id", "date"], keep="last")
        print("silver:", write_silver(df, SCHEMAS["climate"], "climate_daily"), len(df), "rows"); n += 1
    qs = _bronze_files("usgs_earthquakes")
    if qs:
        df = parse_usgs(qs[-1]); print("silver:", write_silver(df, SCHEMAS["quakes"], "quakes"), len(df), "rows"); n += 1
    if n == 0:
        print("Nothing to build. Run `bhunetra ingest ...` first.", file=sys.stderr); return 2
    return 0


def cmd_build_gold(a):
    """Silver climate -> Gold heat features + targets + split, and a label summary report."""
    from bhunetra.features.heat import build_gold_heat, load_yaml
    src = Path("data/silver/climate_daily.parquet")
    if not src.exists():
        print("Missing data/silver/climate_daily.parquet. Run `bhunetra ingest history` then `bhunetra build`.", file=sys.stderr)
        return 2
    th, sp = load_yaml("configs/thresholds.yaml"), load_yaml("configs/split.yaml")
    gold = build_gold_heat(pd.read_parquet(src), th, sp)
    Path("data/gold").mkdir(parents=True, exist_ok=True); Path("reports").mkdir(exist_ok=True)
    gold.to_parquet("data/gold/heat_features.parquet", index=False)
    tg = [f"heat_h{h}" for h in sp["horizons_days"]]
    summ = gold.groupby("split")[tg].agg(["sum", "count"])
    summ.columns = [f"{c}_{k}" for c, k in summ.columns]
    summ.to_csv("reports/heat_label_summary.csv")
    print(f"gold: data/gold/heat_features.parquet {len(gold)} rows, {gold.district_id.nunique()} districts")
    print(summ.to_string())
    return 0


def cmd_train(a):
    """Train heat models and write all results to reports/ (needs data/gold/heat_features.parquet)."""
    if not Path("data/gold/heat_features.parquet").exists():
        print("Missing gold table. Run `bhunetra build-gold` first.", file=sys.stderr); return 2
    from bhunetra.models.heat_pipeline import run
    run("data", "reports", fast=a.fast)
    print("done: see reports/heat_results.md")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bhunetra")
    sub = ap.add_subparsers(required=True)
    i = sub.add_parser("ingest"); i.add_argument("what", choices=["boundaries", "states", "weather", "air", "quakes", "history"])
    i.add_argument("--limit", type=int, help="only first N districts"); i.add_argument("--days", type=int, default=30)
    i.add_argument("--sample", action="store_true", help="only the stratified study sample")
    i.add_argument("--first-year", type=int, default=2020); i.add_argument("--last-year", type=int, default=2024)
    i.add_argument("--budget", type=float, default=8000, help="estimated API-call budget per run")
    i.set_defaults(fn=cmd_ingest)
    t = sub.add_parser("train"); t.add_argument("--fast", action="store_true", help="1 seed, no rolling origin"); t.set_defaults(fn=cmd_train)
    sub.add_parser("build-gold").set_defaults(fn=cmd_build_gold)
    b = sub.add_parser("build-districts"); b.add_argument("--n", type=int, default=60); b.set_defaults(fn=cmd_build_districts)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    a = ap.parse_args(argv); return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
