# Security notes

## Threat model

Defended:

- `AnomalyScorer.update` validates `bucket` and `counts` types, rejects non-string or over-512-character keys, rejects negative, boolean or non-integer counts, rejects more than 100,000 keys in one update, and rejects buckets that are not strictly greater than the previous bucket.
- Constructor options are validated: `window >= min_history`, `min_history >= 3`, `max_keys >= 1`, `threshold > 0`, `mad_floor > 0`, and finite numeric thresholds. Failures raise `AnomalyError('invalid_options')`.
- Tracked state is bounded by `max_keys`. When a new key would exceed the bound, the key whose last non-zero bucket is oldest is evicted; ties are broken by smallest key. The optional `on_event` callback receives metadata only, for example `{'event': 'evicted', 'key': key}`, never log text.
- `from_json` enforces `max_chars` (default 10,000,000), rejects JSON constants such as NaN and Infinity through `parse_constant`, validates option and history shapes, and raises `AnomalyError('invalid_state')` on malformed state.
- Bucket gaps are filled with zeros only for at most `window` buckets, so a very large gap does not cause an unbounded walk through skipped buckets.
- The CLI reports usage, empty-line, invalid-JSON, invalid-field and update errors to stderr and returns exit status 2; it returns 1 when anomalies are printed and 0 otherwise.
- The module uses no `eval`, `exec`, shell commands, network access or third-party runtime dependencies. It attaches a `NullHandler` to its logger.

Not defended:

- The library does not authenticate or authorise callers, encrypt persisted JSON state, or control how callers store or display keys and anomaly output.
- Key text is checked for type and length only; it is not sanitised for terminal control characters, HTML, SQL or other downstream formats.
- `on_event` is called synchronously and exceptions from that callback are not caught by the scorer.
- A scorer instance is mutable and is not documented as thread-safe or process-safe.
- The CLI reads a caller-supplied file path and does not impose a total file-size or line-count limit; per-update key limits and `from_json` character limits are the only size bounds in the code.
- The library does not parse raw logs, extract templates, classify log semantics, or protect log contents; it operates on keyed counts supplied by the caller.

## Publishing

No release credentials or publishing automation are present in the provided source. Do not store long-lived release tokens in the repository; use the project's separate release tooling when publishing.
