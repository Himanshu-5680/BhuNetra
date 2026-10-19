# DATA_SOURCES.md

Checked against official docs on **2026-10-07**. "Confirm in Phase 2" means the
endpoint/terms were seen but a live request has not been made yet.

| # | Layer | Source | Key? | License / terms | Resolution | Known limits |
|---|---|---|---|---|---|---|
| 1 | Weather forecast | Open-Meteo Forecast | No | CC BY 4.0, free for non-commercial use only | Model grid, hourly | Commercial use needs a paid plan |
| 2 | Historical weather | Open-Meteo Archive (ERA5-based) | No | CC BY 4.0, non-commercial | Hourly, 1940-present (per Open-Meteo) | Reanalysis, not station readings. Confirm in Phase 2 |
| 3 | Air quality (core) | Open-Meteo Air Quality (CAMS) | No | CC BY 4.0; credit CAMS ENSEMBLE + Open-Meteo | ~45 km global model for India (11 km is Europe only) | **Model output, not sensors.** Coarse. Past data limited to `past_days` up to 92 |
| 4 | Air quality (stations) | OpenAQ v3 | **Yes, free** (`X-API-Key`) | Per data provider | Station points | Sparse in rural districts. Optional layer |
| 5 | Active fires | NASA FIRMS | **Yes, free MAP_KEY** | NASA open data. Confirm wording in Phase 2 | VIIRS/MODIS pixels | Satellite overpass gaps, cloud cover. Optional layer unless key set |
| 6 | Earthquakes | USGS FDSN Event | No | US Gov. Confirm wording in Phase 2 | Event points | Max 20,000 events per query. **Cannot be predicted** |
| 7 | Boundaries | geoBoundaries India ADM1/ADM2 via HDX | No | ODbL (HDX listing) | District polygons | Boundary disclaimer needed. Names may differ from Census/LGD |
| 8 | Population | WorldPop India 2020 | No | CC BY 4.0 | 1 km or 100 km grids (100 m file is ~500 MB) | Modelled estimate, not census |

## Not in v1 (and why)
- **IMD rainfall and GPM IMERG:** access terms not verified yet. Rain will come from Open-Meteo for now. Added later only if terms allow.
- **NASA POWER:** not needed while Open-Meteo Archive covers history.
- **CPCB direct feed:** not checked.

## Rule for keys
Core app must run with **no keys**. Without keys the fire and station layers
show "key not configured" or a dated offline snapshot, never fake data.
