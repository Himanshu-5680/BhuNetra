Run in order (internet needed). Phase 2 data stays; this adds states, districts, history.

bhunetra ingest boundaries
bhunetra ingest states
bhunetra build-districts          # prints districts per state + the study sample
bhunetra ingest history --first-year 2020 --last-year 2024
bhunetra build
python -m pytest -q tests/test_phase2.py tests/test_phase3a.py
