# log-anomaly-score

[![PyPI version](https://img.shields.io/pypi/v/trysac-log-anomaly-score)](https://pypi.org/project/trysac-log-anomaly-score/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-log-anomaly-score)](LICENSE)
[![CI](https://github.com/Trysac/u234-log-anomaly-score/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u234-log-anomaly-score/actions/workflows/ci.yml)

Score anomalies in per-bucket log counts with robust z-scores over a trailing window: median and MAD baselines, spikes, drops, new keys and bounded JSON state

## Problem

A log pattern that suddenly appears 40 times a minute, or an expected heartbeat line that stops, is often an early incident signal, but static count thresholds are noisy or blind. Mean and standard deviation baselines are dragged by the outliers they should detect. This library keeps a trailing window of counts per key (a log template, level or service) and scores each new bucket with the median absolute deviation (MAD) method of Iglewicz and Hoaglin. It uses only the Python standard library.

## Install

```sh
pip install trysac-log-anomaly-score
```

Requires Python 3.10 or newer. The distribution name is `trysac-log-anomaly-score`; the import name is `log_anomaly_score`.

## Usage

```python
from log_anomaly_score import AnomalyScorer, bucketize

scorer = AnomalyScorer(window=5, min_history=5)
for bucket, count in enumerate([10, 12, 11, 13, 12]):
    scorer.update(bucket, {"db_timeout": count})
print(scorer.update(5, {"db_timeout": 20}))
print(bucketize([(0.5, "a"), (59.9, "a"), (60.0, "b")], 60))
```

## Public API

`AnomalyScorer(*, window=24, threshold=3.5, mad_floor=1.0, min_history=5, max_keys=10_000, on_event=None)` scores per-bucket keyed counts. `update(bucket, counts)` returns `list[Anomaly]`; `len(scorer)` returns the number of tracked keys; `to_json()` returns a JSON string; `from_json(text, *, max_chars=10_000_000)` restores a scorer.

`Anomaly` is a frozen dataclass with fields `key: str`, `bucket: int`, `count: int`, `median: float | None`, `mad: float | None`, `score: float | None`, and `kind: 'spike' | 'drop' | 'new'`. New keys have `median`, `mad` and `score` set to `None`.

`bucketize(events, bucket_seconds)` takes `(timestamp, key)` pairs and returns `dict[int, dict[str, int]]` using `floor(timestamp / bucket_seconds)`. It raises `ValueError` if `bucket_seconds` is not positive.

`main(argv=None)` runs the CLI `score <counts.jsonl> [--window 24] [--threshold 3.5]`. Each input line is `{'bucket': int, 'counts': {key: int}}`; output is `bucket<TAB>key<TAB>kind<TAB>count<TAB>score`, with score to three decimals or `-` for new keys. Exit status is 0 when no anomalies are printed, 1 when anomalies are printed, and 2 on usage or input errors.

Options are validated: `window >= min_history`, `min_history >= 3`, `max_keys >= 1`, `threshold > 0`, and `mad_floor > 0`; threshold and `mad_floor` must be finite. Invalid options raise `AnomalyError('invalid_options')`.

Errors use `AnomalyError(code)`, a `ValueError` subclass, with codes `out_of_order`, `invalid_count`, `invalid_key`, `too_many_keys`, `invalid_options`, `invalid_state`, and `input_too_large`. `bucketize` raises built-in `ValueError`; `update` raises built-in `TypeError` when `bucket` is not an `int` or `counts` is not a mapping.

Limits: keys longer than 512 characters raise `invalid_key`; a single `update` accepts at most 100,000 keys and otherwise raises `too_many_keys`; `max_keys` bounds tracked keys and evicts the key whose last non-zero bucket is oldest (ties by smallest key), emitting `{'event': 'evicted', 'key': key}` when `on_event` is set. `from_json` rejects input longer than `max_chars` and rejects invalid JSON state. Gaps fill at most `window` zero-count buckets for known keys. Events contain only event metadata, never log text.

## Why not mean and standard deviation alerts or a template miner

Median and MAD resist the outliers being detected, while mean and standard deviation are dragged by them. The scorer works on any keyed counts; extracting templates from raw log lines, seasonality models, and multi-key correlation are out of scope.

## Documentation

- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
