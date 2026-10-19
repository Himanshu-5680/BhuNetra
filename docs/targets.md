# Targets (draft v0.1, Phase 3)

## Heat-stress target (first target to build)
`heat_event(d, t)` = 1 if district `d` meets the IMD-style rule on day `t`, else 0:
- Tmax >= 40 C (plains) AND (Tmax - normal_Tmax) >= 4.5 C, OR Tmax >= 45 C.
- Severe: departure > 6.4 C OR Tmax >= 47 C.
- Rule source: IMD Morning Heat Bulletin (see `configs/thresholds.yaml`).

### Honest differences from IMD's official declaration
1. We use ERA5-based grid temperature, not station readings.
2. IMD requires the rule at >=2 stations for >=2 consecutive days; we flag single district-days.
3. Our "normal" is learned from the TRAIN years only (2020-2022, +/-7 day window, 365-day calendar),
   because using 2023-2024 would leak test information into the labels. IMD uses 1991-2020. A short normal
   is noisy and, because India is warming, makes later years look hotter relative to it.
   (Changed from the first draft, which said 2020-2024.)
4. All districts treated as plains in v1.
Heat events are rare and strongly seasonal (March-June), so we report PR-AUC/recall, not accuracy,
and evaluate per season.

## Not yet defined (needs source reading first)
- Rain / flood indicator, AQI category target, fire proximity.
- Earthquakes: context only (cannot be predicted).

## Prediction task (v1, heat)
Issue day `t`, using only data up to the end of day `t`, predict `heat_event` on day `t+1`, `t+2`, `t+3`.
Columns: `heat_h1`, `heat_h2`, `heat_h3`. No weather-forecast inputs are used in training because a
historical archive of past forecasts has not been verified, so v1 skill beyond a few days is expected to be limited.

## Split (configs/split.yaml)
train = issue days up to 2022-12-31, valid = 2023, test = 2024. Rows whose farthest target day crosses
into the next split are `purged` (360 rows). Real counts (reports/heat_label_summary.csv):
train 403 positive of 65,220 (0.62%), valid 253 of 21,720 (1.16%), test 615 of 21,780 (2.82%).
The base rate rises 4.5x from train to test: 2024 was a much hotter year, so test is a hard distribution shift.

## Known baseline fact (measured on the gold table)
P(heat tomorrow | heat today) = 0.697, P(heat tomorrow | no heat today) = 0.0036.
A persistence baseline is therefore strong; the model must be judged on ONSET events too
(no heat today, heat tomorrow), not only on overall scores.

## Leakage controls and the tests that prove them (tests/test_phase3b.py)
1. Features use trailing windows only. Tests delete or change all days after T; features up to T must not move.
2. Normal uses train years only. Test changes post-train data; the normal must not move.
3. Split purge. Test checks no target day reaches into a later split.
Each control was checked by deliberately breaking it (centered window, normal from all years, no purge);
the tests failed every time, and passed again when restored.
Remaining in-sample effect: for TRAIN rows the normal includes the row itself, for valid/test it does not.
