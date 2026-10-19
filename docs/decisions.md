# Decisions log

## D1. Default heat model = logistic regression (3 features), not LightGBM
- Date: 2026-10-13. Status: adopted, configured in `configs/models.yaml`.
- Why: it had the best PR-AUC in 2024 test (0.797 vs 0.741 LightGBM at 1 day), and in the 2023 valid year
  (0.656 vs 0.562). LightGBM was also behind in the rolling and unseen-state checks.
- Honesty note: I first looked at 2024 test numbers, then checked valid. So valid is a confirmation,
  not a clean selection. The default is refit on train+valid before predictions.
- LightGBM stays in the repo as a comparison, not the default.
- Not solved: both models are weak on ONSET days (no heat today, heat later). Recall at the F1-optimal threshold (2024):
  LightGBM 12% / 12% / 23%, logistic 19% / 11% / 25% for 1 / 2 / 3 days; logistic precision there is only 23-26%.
  (An earlier version of this note wrongly said the logistic number was not measured; it was in reports/heat_results.md.)

## D2. Research prototype, not a public warning system
- The model uses only past data and historical grid temperature. It has no forecast inputs and is not validated
  against official IMD warnings. Any public use needs its own validation and review.
