# Testing

## Running

Run the repository test module with `pytest` from the repository root. The provided tests are in `tests/test_log_anomaly_score.py`; no conformance harness or external-tool setup is present in the provided source.

## Policy

The tests use pytest and exercise the public `log_anomaly_score` API. They are deterministic unit tests: no network access, wall-clock dependence or test-order dependence is defined in the test module. No coverage threshold is recorded in the provided source.

## Tiers

The provided tests are local unit tests only. No `@pytest.mark.conformance` tests and no external-tool download setup are present in the supplied test artifact.

## Layout

`tests/test_log_anomaly_score.py` contains `_fill_warm_up`, which feeds five identical buckets to satisfy the default `min_history`, plus two test classes. `TestAnomalyScorerConstruct` contains `test_valid_defaults` and `test_invalid_options`; it covers default construction and rejection of invalid options. `TestUpdateAcceptance` includes tests visible as `test_spike`, `test_drop`, `test_no_anomaly` and `test_missing_key_scores_count_zero`; these cover robust spike and drop scores, the no-anomaly case, and scoring a missing key as count 0. No `conftest.py` is present in the provided source.
