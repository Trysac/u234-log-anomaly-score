# Project record

## Objective

Score anomalies in per-bucket log counts with robust z-scores over a trailing window. The module keeps median/MAD baselines per key, reports spikes, drops and newly seen keys, bounds state with `max_keys`, and serialises state to JSON. Its public API is `AnomalyScorer`, `Anomaly`, `AnomalyError`, `bucketize` and `main`.

## Scope

- In scope: the `log_anomaly_score` package with a typed public API; per-key trailing-window counts; robust z-score `0.6745 * (count - median) / max(mad, mad_floor)`; `spike` when score >= threshold and `drop` when score <= -threshold; `new` keys after warm-up; zero filling for bucket gaps; bounded tracked keys with eviction based on the oldest last non-zero bucket; JSON state with `to_json` and `from_json`; `bucketize`; and the `score` CLI.
- Out of scope: extracting templates from raw log lines (feed counts from any template miner), seasonality models, multi-key correlation, runtime dependencies, authentication, authorisation, and log storage or transport.

## Timeline

| Date | Event |
|---|---|
| Not recorded in the provided source | Repository history is not present in the code or specification. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 5004898 / 303575 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.4722 |

## Factory run u234 (measured from API usage)

| Date (UTC) | Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| 2026-11-10 | generation | deepseek-v4-pro | yes | 1917 | 25720 | 0 | 3200 | 0.0523 |
| 2026-11-10 | fix-1 | deepseek-flash | no | 35057 | 56519 | 0 | 1220736 | 0.0428 |
| 2026-11-10 | fix-2 | deepseek-flash | no | 19669 | 20649 | 0 | 439296 | 0.0167 |
| 2026-11-10 | fix-3 | deepseek-flash | no | 40323 | 30843 | 0 | 935296 | 0.0274 |
| 2026-11-10 | fix-4 | deepseek-flash | no | 30565 | 31083 | 0 | 783104 | 0.0256 |
| 2026-11-11 | fix-1 | deepseek-v4-pro | no | 41642 | 33934 | 0 | 323072 | 0.1018 |
| 2026-11-11 | fix-2 | deepseek-v4-pro | no | 4460 | 1568 | 0 | 37376 | 0.0069 |
| 2026-11-11 | fix-3 | deepseek-v4-pro | no | 8991 | 38849 | 0 | 232960 | 0.0880 |
| 2026-11-11 | fix-4 | deepseek-v4-pro | no | 9303 | 14504 | 0 | 119424 | 0.0375 |
| 2026-11-11 | audit | deepseek-flash | no | 20547 | 29391 | 0 | 489472 | 0.0222 |
| 2026-11-11 | fix-1 | deepseek-v4-pro | no | 13113 | 10422 | 0 | 105088 | 0.0316 |
| 2026-11-11 | docs | deepseek-flash | no | 90031 | 10093 | 0 | 256 | 0.0196 |

Total: $0.4722. Prices: deepseek line, as measured by its adapter. Providers serve the current version of each model id, so the date tells which version answered; versions, launch stages and price sources per line are in the factory's model register (docs/MODELS.md).
