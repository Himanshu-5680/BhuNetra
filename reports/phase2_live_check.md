# Phase 2 live check (run on YOUR machine, needs internet)

Python 3.11+ required.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

bhunetra ingest boundaries         # real district polygons (~8 MB)
bhunetra ingest weather --limit 20 # first 20 districts only, quick test
bhunetra ingest air --limit 20
bhunetra ingest quakes --days 30
bhunetra build                     # Bronze -> validated Silver parquet
python -m pytest -q tests/test_phase2.py
```

Expected: files in data/bronze/<source>/ with `.meta.json`, parquet in data/silver/.
Paste back: terminal output, and `python -c "import pandas as pd; print(pd.read_parquet('data/silver/weather.parquet').describe())"`
Any schema error is a real finding. Tell me and I fix the contract.
