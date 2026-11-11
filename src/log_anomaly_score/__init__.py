"""Anomaly scoring for per-bucket log counts using robust z-scores.

This module keeps a trailing window of counts per key and scores each new
bucket with the median absolute deviation (MAD), as described by Iglewicz
and Hoaglin.  Spikes, drops, and newly seen keys are reported, with bounded
state and JSON serialisation for persistence.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
import sys
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "Anomaly",
    "AnomalyError",
    "AnomalyScorer",
    "bucketize",
    "main",
]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_ErrorCode = Literal[
    "out_of_order",
    "invalid_count",
    "invalid_key",
    "too_many_keys",
    "invalid_options",
    "invalid_state",
    "input_too_large",
]
_Kind = Literal["spike", "drop", "new"]


class AnomalyError(ValueError):
    """Error raised for invalid input or state.

    Attributes:
        code: Stable machine-readable error code, one of the
            ``_ErrorCode`` literals.
    """

    def __init__(self, code: _ErrorCode) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Anomaly:
    """A single detected anomaly.

    Attributes:
        key: The key (log template, level, service) that was scored.
        bucket: The integer bucket in which the anomaly occurred.
        count: The observed count for ``key`` in ``bucket``.
        median: Median of the trailing history, or ``None`` for new keys.
        mad: Median absolute deviation of the history, or ``None`` for new keys.
        score: Robust z-score, or ``None`` for new keys.
        kind: ``'spike'`` if score >= threshold, ``'drop'`` if score <=
            -threshold, otherwise ``'new'`` for keys with no history.
    """

    key: str
    bucket: int
    count: int
    median: float | None
    mad: float | None
    score: float | None
    kind: _Kind


class AnomalyScorer:
    """Score anomalies in per-bucket keyed counts.

    Args:
        window: Number of trailing buckets to keep per key.  Must be >=
            ``min_history``.
        threshold: Score magnitude that triggers a spike (>= threshold) or
            drop (<= -threshold).
        mad_floor: Floor applied to MAD to avoid division by zero.
        min_history: Number of buckets the scorer must observe before it
            starts emitting anomalies.  Must be at least 3.
        max_keys: Maximum number of tracked keys.  When a new key would
            exceed this, the key whose last non-zero bucket is oldest is
            evicted (ties broken by smallest key).
        on_event: Optional callback receiving metadata dictionaries, e.g.
            ``{"event": "evicted", "key": "a"}``.  Never contains log text.

    Raises:
        AnomalyError: If the constructor options fail validation, with code
            ``'invalid_options'``.
    """

    def __init__(
        self,
        *,
        window: int = 24,
        threshold: float = 3.5,
        mad_floor: float = 1.0,
        min_history: int = 5,
        max_keys: int = 10_000,
        on_event: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        if (
            isinstance(window, bool)
            or not isinstance(window, int)
            or isinstance(min_history, bool)
            or not isinstance(min_history, int)
            or isinstance(max_keys, bool)
            or not isinstance(max_keys, int)
            or not isinstance(threshold, int | float)
            or isinstance(threshold, bool)
            or not isinstance(mad_floor, int | float)
            or isinstance(mad_floor, bool)
        ):
            raise AnomalyError("invalid_options")
        if (
            window < min_history
            or min_history < 3
            or max_keys < 1
            or threshold <= 0
            or mad_floor <= 0
            or not math.isfinite(threshold)
            or not math.isfinite(mad_floor)
        ):
            raise AnomalyError("invalid_options")

        self._window = window
        self._threshold = threshold
        self._mad_floor = mad_floor
        self._min_history = min_history
        self._max_keys = max_keys
        self._on_event = on_event
        self._histories: dict[str, deque[int]] = {}
        self._last_bucket: int | None = None
        self._buckets_seen = 0

    def __len__(self) -> int:
        """Return the number of currently tracked keys."""
        return len(self._histories)

    def update(self, bucket: int, counts: Mapping[str, int]) -> list[Anomaly]:
        """Process one bucket and return anomalies for it.

        Args:
            bucket: Integer bucket identifier.  Must be strictly greater than
                the previous bucket; gaps are filled with zero counts for all
                known keys.
            counts: Mapping of key to non-negative integer count.

        Returns:
            List of :class:`Anomaly` objects, sorted as spiked/drops by
            descending |score| then key, followed by new-key anomalies sorted
            by key.

        Raises:
            AnomalyError: With codes ``'out_of_order'``, ``'invalid_count'``,
                ``'invalid_key'``, or ``'too_many_keys'``.
        """
        if isinstance(bucket, bool) or not isinstance(bucket, int):
            raise TypeError("bucket must be an int")
        if not isinstance(counts, Mapping):
            raise TypeError("counts must be a mapping")
        if len(counts) > 100_000:
            raise AnomalyError("too_many_keys")

        for key, value in counts.items():
            if not isinstance(key, str):
                raise AnomalyError("invalid_key")
            if len(key) > 512:
                raise AnomalyError("invalid_key")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AnomalyError("invalid_count")

        if self._last_bucket is not None:
            if bucket <= self._last_bucket:
                raise AnomalyError("out_of_order")
            if bucket > self._last_bucket + 1:
                # Fill skipped buckets with zeros for every known key.  Only
                # the last ``window`` buckets can matter, so enormous gaps do
                # not need to be walked one bucket at a time.
                gap = bucket - self._last_bucket - 1
                for _ in range(min(gap, self._window)):
                    for history in self._histories.values():
                        history.append(0)
                self._last_bucket = bucket - 1
                self._buckets_seen += gap

        anomalies: list[Anomaly] = []
        score_current = self._buckets_seen >= self._min_history

        if score_current:
            for key in set(self._histories) | set(counts):
                count = counts.get(key, 0)
                if key not in self._histories:
                    anomalies.append(
                        Anomaly(
                            key=key,
                            bucket=bucket,
                            count=count,
                            median=None,
                            mad=None,
                            score=None,
                            kind="new",
                        )
                    )
                else:
                    anomaly = self._score_existing(key, bucket, count)
                    if anomaly is not None:
                        anomalies.append(anomaly)

            anomalies = self._sort_anomalies(anomalies)

        self._advance_histories(bucket, counts)
        return anomalies

    def _score_existing(self, key: str, bucket: int, count: int) -> Anomaly | None:
        history = list(self._histories[key])
        median = float(statistics.median(history))
        deviations = [abs(h - median) for h in history]
        mad = statistics.median(deviations)
        score = 0.6745 * (count - median) / max(mad, self._mad_floor)
        if score >= self._threshold:
            return Anomaly(
                key=key,
                bucket=bucket,
                count=count,
                median=median,
                mad=mad,
                score=score,
                kind="spike",
            )
        if score <= -self._threshold:
            return Anomaly(
                key=key,
                bucket=bucket,
                count=count,
                median=median,
                mad=mad,
                score=score,
                kind="drop",
            )
        return None

    @staticmethod
    def _sort_anomalies(anomalies: list[Anomaly]) -> list[Anomaly]:
        def sort_key(item: Anomaly) -> tuple[int, float, str]:
            if item.kind in ("spike", "drop"):
                return (0, -abs(item.score or 0.0), item.key)
            return (1, 0.0, item.key)

        return sorted(anomalies, key=sort_key)

    def _advance_histories(self, bucket: int, counts: Mapping[str, int]) -> None:
        for key in list(self._histories):
            self._histories[key].append(counts.get(key, 0))

        for key, count in counts.items():
            if key in self._histories:
                continue
            # Insert zeros for all buckets observed before this key existed
            # so its median correctly reflects absence during those buckets.
            past_count = min(self._buckets_seen, self._window)
            history: deque[int] = deque([0] * past_count, maxlen=self._window)
            history.append(count)
            self._histories[key] = history

        self._last_bucket = bucket
        self._buckets_seen += 1

        while len(self._histories) > self._max_keys:
            self._evict_one()

    def _evict_one(self) -> None:
        last_bucket = self._last_bucket if self._last_bucket is not None else -1

        def eviction_key(item: tuple[str, deque[int]]) -> tuple[float, str]:
            key, history = item
            last_nonzero: int | None = None
            for offset, value in enumerate(reversed(history)):
                if value != 0:
                    last_nonzero = last_bucket - offset
                    break
            # A key with no non-zero count in the window is treated as older
            # than every key that has one.
            age = float("-inf") if last_nonzero is None else float(last_nonzero)
            return (age, key)

        key, _ = min(self._histories.items(), key=eviction_key)
        del self._histories[key]
        self._emit({"event": "evicted", "key": key})

    def _emit(self, event: dict[str, object]) -> None:
        if self._on_event is not None:
            self._on_event(event)

    def to_json(self) -> str:
        """Serialise scorer state to a JSON string.

        The string includes options, the last bucket, the number of buckets
        seen (for warm-up continuity), and the per-key histories.
        """
        data = {
            "options": {
                "window": self._window,
                "threshold": self._threshold,
                "mad_floor": self._mad_floor,
                "min_history": self._min_history,
                "max_keys": self._max_keys,
            },
            "last_bucket": self._last_bucket,
            "seen_buckets": self._buckets_seen,
            "histories": {key: list(history) for key, history in self._histories.items()},
        }
        return json.dumps(data, sort_keys=True)

    @classmethod
    def from_json(cls, text: str, *, max_chars: int = 10_000_000) -> AnomalyScorer:
        """Deserialise a scorer previously written by :meth:`to_json`.

        Args:
            text: JSON string produced by :meth:`to_json`.
            max_chars: Maximum accepted input length.  Raises
                :class:`AnomalyError` with code ``'input_too_large'`` if
                exceeded.

        Returns:
            A new :class:`AnomalyScorer` with identical state.

        Raises:
            AnomalyError: With codes ``'input_too_large'`` or
                ``'invalid_state'``.
        """
        if len(text) > max_chars:
            raise AnomalyError("input_too_large")

        def _reject_constant(_value: str) -> None:
            raise AnomalyError("invalid_state")

        try:
            data = json.loads(text, parse_constant=_reject_constant)
        except (json.JSONDecodeError, AnomalyError) as exc:
            raise AnomalyError("invalid_state") from exc

        if not isinstance(data, dict):
            raise AnomalyError("invalid_state")

        options = data.get("options")
        if not isinstance(options, dict):
            raise AnomalyError("invalid_state")

        def _get_int(name: str) -> int:
            value = options.get(name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise AnomalyError("invalid_state")
            return value

        def _get_float(name: str) -> float:
            value = options.get(name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise AnomalyError("invalid_state")
            return float(value)

        window = _get_int("window")
        threshold = _get_float("threshold")
        mad_floor = _get_float("mad_floor")
        min_history = _get_int("min_history")
        max_keys = _get_int("max_keys")

        last_bucket = data.get("last_bucket")
        if last_bucket is not None and (
            isinstance(last_bucket, bool) or not isinstance(last_bucket, int)
        ):
            raise AnomalyError("invalid_state")

        seen_buckets = data.get("seen_buckets")
        if seen_buckets is None:
            seen_buckets = last_bucket + 1 if last_bucket is not None else 0
        if isinstance(seen_buckets, bool) or not isinstance(seen_buckets, int) or seen_buckets < 0:
            raise AnomalyError("invalid_state")

        histories = data.get("histories")
        if not isinstance(histories, dict) or len(histories) > max_keys:
            raise AnomalyError("invalid_state")

        try:
            scorer = cls(
                window=window,
                threshold=threshold,
                mad_floor=mad_floor,
                min_history=min_history,
                max_keys=max_keys,
            )
        except AnomalyError as exc:
            raise AnomalyError("invalid_state") from exc

        for key, history_list in histories.items():
            if len(key) > 512:
                raise AnomalyError("invalid_state")
            if not isinstance(history_list, list) or not history_list:
                raise AnomalyError("invalid_state")
            if len(history_list) > window:
                raise AnomalyError("invalid_state")
            for value in history_list:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise AnomalyError("invalid_state")
            scorer._histories[key] = deque(history_list[-window:], maxlen=window)
        scorer._last_bucket = last_bucket
        scorer._buckets_seen = seen_buckets
        return scorer


def bucketize(
    events: Iterable[tuple[float, str]],
    bucket_seconds: int,
) -> dict[int, dict[str, int]]:
    """Aggregate timestamped events into plain dict of bucket -> key -> count.

    Args:
        events: Iterable of ``(timestamp, key)`` pairs.  Timestamps are
            floats (Unix seconds).
        bucket_seconds: Width of each bucket in seconds.

    Returns:
        Mapping from bucket (``floor(timestamp / bucket_seconds)``) to a
        mapping of key to event count.

    Raises:
        ValueError: If ``bucket_seconds`` is not positive.
    """
    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds must be positive")
    buckets: dict[int, dict[str, int]] = {}
    for timestamp, key in events:
        bucket = math.floor(timestamp / bucket_seconds)
        bucket_counts = buckets.setdefault(bucket, {})
        bucket_counts[key] = bucket_counts.get(key, 0) + 1
    return buckets


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface.

    Usage::

        score <counts.jsonl> [--window 24] [--threshold 3.5]

    Each line of the JSONL input is ``{"bucket": int, "counts": {key: int}}``.
    Output lines are ``bucket<TAB>key<TAB>kind<TAB>count<TAB>score`` where score
    is formatted to three decimals or ``-`` for new keys.

    Returns:
        0 if no anomalies, 1 if anomalies were printed, 2 on usage or input
        errors.
    """
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] != "score":
        print(
            "usage: score <counts.jsonl> [--window 24] [--threshold 3.5]",
            file=sys.stderr,
        )
        return 2

    window = 24
    threshold = 3.5
    path: str | None = None
    args = list(argv[1:])
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--window":
            if i + 1 >= len(args):
                return 2
            try:
                window = int(args[i + 1])
            except ValueError:
                return 2
            i += 2
        elif arg == "--threshold":
            if i + 1 >= len(args):
                return 2
            try:
                threshold = float(args[i + 1])
            except ValueError:
                return 2
            i += 2
        elif arg.startswith("-"):
            return 2
        else:
            if path is not None:
                return 2
            path = arg
            i += 1

    if path is None:
        return 2

    try:
        scorer = AnomalyScorer(
            window=window,
            threshold=threshold,
            min_history=min(5, window),
        )
    except AnomalyError:
        return 2

    any_anomaly = False
    try:
        with open(path, encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                stripped = line.strip()
                if not stripped:
                    print(f"error: empty line {line_number}", file=sys.stderr)
                    return 2
                try:
                    item = json.loads(stripped)
                except json.JSONDecodeError:
                    print(f"error: invalid JSON on line {line_number}", file=sys.stderr)
                    return 2
                if not isinstance(item, dict):
                    print(f"error: line {line_number} is not a JSON object", file=sys.stderr)
                    return 2
                bucket = item.get("bucket")
                counts = item.get("counts")
                if isinstance(bucket, bool) or not isinstance(bucket, int):
                    print(f"error: invalid bucket on line {line_number}", file=sys.stderr)
                    return 2
                if not isinstance(counts, dict):
                    print(f"error: invalid counts on line {line_number}", file=sys.stderr)
                    return 2
                try:
                    anomalies = scorer.update(bucket, counts)
                except AnomalyError as exc:
                    print(f"error: {exc.code} on line {line_number}", file=sys.stderr)
                    return 2
                for anomaly in anomalies:
                    any_anomaly = True
                    score_text = "-" if anomaly.score is None else f"{anomaly.score:.3f}"
                    print(
                        f"{anomaly.bucket}\t{anomaly.key}\t{anomaly.kind}\t"
                        f"{anomaly.count}\t{score_text}"
                    )
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return 1 if any_anomaly else 0
