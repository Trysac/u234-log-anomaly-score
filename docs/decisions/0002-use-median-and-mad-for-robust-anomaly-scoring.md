# Use median and MAD for robust anomaly scoring

Status: accepted (generated, pending human review)

## Context

Static count thresholds are noisy; mean and standard deviation are affected by the outliers they should detect. We need a detector that works on arbitrary keyed per-bucket counts from log template miners.

## Decision

Implement an AnomalyScorer that keeps a trailing window of counts and scores each bucket with 0.6745*(count-median)/max(MAD, mad_floor), reporting spikes, drops, and new keys. State is bounded by max_keys with LRU-like eviction, and gaps are filled with zeros.

## Consequences

The detector is robust to outliers and works with any keyed count source. It has no runtime dependencies, serialises to JSON, and includes a CLI. Seasonality and correlation are explicitly out of scope.
