# Live ingestion run report

**Status: live ingestion RAN, on the author's Colab, on 2026-10-08/09.** (The build sandbox itself cannot
reach the data hosts, so the author ran the commands and shared the resulting `data/` folder.)

What was checked from that real data (by the assistant, from the shared zip):
- Boundaries: 735 districts (geoBoundaries ADM2), 35 states/UTs assigned, 1 unassigned (Lakshadweep, left empty on purpose).
- Weather + air (20 MP districts, 10 days) and earthquakes (35 events, 30 days): schema checks passed.
- History (Open-Meteo archive, ERA5-based): 60 sampled districts x 2020-2024 = 109,620 daily rows,
  30 of 30 batches complete, 0 duplicates, 0 missing values, 0 checksum mismatches.
- Not verified: the exact Open-Meteo rate-limit rule. A first run hit HTTP 429 after ~1,000 estimated calls
  in under a minute; pacing (about 39 s between batches) fixed it. The reason for the 429 was never read from the server.

Re-run: see `reports/phase3a_live_steps.md`.
