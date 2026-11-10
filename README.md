# log-anomaly-score

[![PyPI version](https://img.shields.io/pypi/v/trysac-log-anomaly-score)](https://pypi.org/project/trysac-log-anomaly-score/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-log-anomaly-score)](LICENSE)
[![CI](https://github.com/Trysac/u234-log-anomaly-score/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u234-log-anomaly-score/actions/workflows/ci.yml)

Score anomalies in per-bucket log counts with robust z-scores over a trailing window: median and MAD baselines, spikes, drops, new keys and bounded JSON state

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-log-anomaly-score
# or
uv add trysac-log-anomaly-score
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import log_anomaly_score

# normalize() trims surrounding whitespace and lower-cases the text.
print(log_anomaly_score.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    log_anomaly_score.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
