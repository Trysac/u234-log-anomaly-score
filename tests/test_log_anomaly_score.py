from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from log_anomaly_score import AnomalyError, AnomalyScorer, bucketize, main


def _fill_warm_up(scorer: AnomalyScorer, count: int = 1) -> None:
    """Feed five identical buckets to satisfy the default min_history."""
    for bucket in range(5):
        scorer.update(bucket, {"existing": count})


class TestAnomalyScorerConstruct:
    def test_valid_defaults(self) -> None:
        scorer = AnomalyScorer()
        assert len(scorer) == 0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"window": 2, "min_history": 3},
            {"window": 5, "min_history": 2},
            {"threshold": 0},
            {"mad_floor": 0},
            {"max_keys": 0},
            {"threshold": "3.5"},
            {"mad_floor": "1.0"},
            {"threshold": float("nan")},
            {"threshold": float("inf")},
            {"mad_floor": float("nan")},
            {"mad_floor": float("inf")},
        ],
    )
    def test_invalid_options(self, kwargs: dict[str, object]) -> None:
        with pytest.raises(AnomalyError) as exc_info:
            AnomalyScorer(**kwargs)
        assert exc_info.value.code == "invalid_options"


class TestUpdateAcceptance:
    def test_spike(self) -> None:
        scorer = AnomalyScorer(window=5, threshold=3.5, mad_floor=1.0, min_history=5)
        history_counts = [10, 12, 11, 13, 12]
        for bucket, count in enumerate(history_counts):
            scorer.update(bucket, {"db_timeout": count})
        result = scorer.update(5, {"db_timeout": 20})
        assert len(result) == 1
        anomaly = result[0]
        assert anomaly.key == "db_timeout"
        assert anomaly.bucket == 5
        assert anomaly.count == 20
        assert anomaly.median == 12.0
        assert anomaly.mad == 1.0
        assert abs(anomaly.score - 5.396) < 1e-9
        assert anomaly.kind == "spike"

    def test_drop(self) -> None:
        scorer = AnomalyScorer(window=5, threshold=3.5, mad_floor=1.0, min_history=5)
        for bucket, count in enumerate([10, 12, 11, 13, 12]):
            scorer.update(bucket, {"db_timeout": count})
        result = scorer.update(5, {"db_timeout": 5})
        assert len(result) == 1
        anomaly = result[0]
        assert anomaly.kind == "drop"
        assert abs(anomaly.score + 4.7215) < 1e-9

    def test_no_anomaly(self) -> None:
        scorer = AnomalyScorer(window=5, threshold=3.5, mad_floor=1.0, min_history=5)
        for bucket, count in enumerate([10, 12, 11, 13, 12]):
            scorer.update(bucket, {"db_timeout": count})
        result = scorer.update(5, {"db_timeout": 13})
        assert result == []

    def test_missing_key_scores_count_zero(self) -> None:
        scorer = AnomalyScorer(window=5, threshold=3.5, mad_floor=1.0, min_history=5)
        for bucket, count in enumerate([10, 12, 11, 13, 12]):
            scorer.update(bucket, {"db_timeout": count})
        result = scorer.update(5, {})
        assert len(result) == 1
        assert result[0].count == 0
        assert result[0].kind == "drop"

    def test_mad_floor_prevents_noise(self) -> None:
        scorer = AnomalyScorer(window=5, threshold=3.5, mad_floor=1.0, min_history=5)
        for bucket in range(5):
            scorer.update(bucket, {"stable": 5})
        result = scorer.update(5, {"stable": 9})
        assert result == []

    def test_new_key_after_warmup(self) -> None:
        scorer = AnomalyScorer(window=5, threshold=3.5, mad_floor=1.0, min_history=5)
        _fill_warm_up(scorer)
        result = scorer.update(5, {"brand_new": 3})
        assert len(result) == 1
        anomaly = result[0]
        assert anomaly.key == "brand_new"
        assert anomaly.kind == "new"
        assert anomaly.median is None
        assert anomaly.mad is None
        assert anomaly.score is None

    def test_no_anomalies_during_warmup(self) -> None:
        scorer = AnomalyScorer(window=5, threshold=0.1, mad_floor=1.0, min_history=5)
        for bucket in range(5):
            result = scorer.update(bucket, {"db_timeout": 100 if bucket == 4 else 1})
            assert result == []

    def test_out_of_order(self) -> None:
        scorer = AnomalyScorer()
        scorer.update(5, {"a": 1})
        with pytest.raises(AnomalyError) as exc_info:
            scorer.update(4, {"a": 1})
        assert exc_info.value.code == "out_of_order"

    def test_invalid_count_negative_and_bool(self) -> None:
        scorer = AnomalyScorer()
        with pytest.raises(AnomalyError) as exc_info:
            scorer.update(0, {"a": -1})
        assert exc_info.value.code == "invalid_count"
        with pytest.raises(AnomalyError) as exc_info:
            scorer.update(0, {"a": True})
        assert exc_info.value.code == "invalid_count"

    def test_invalid_key_too_long(self) -> None:
        scorer = AnomalyScorer()
        with pytest.raises(AnomalyError) as exc_info:
            scorer.update(0, {"x" * 513: 1})
        assert exc_info.value.code == "invalid_key"

    def test_too_many_keys(self) -> None:
        scorer = AnomalyScorer()
        counts = {f"key_{i}": 1 for i in range(100_001)}
        with pytest.raises(AnomalyError) as exc_info:
            scorer.update(0, counts)
        assert exc_info.value.code == "too_many_keys"

    def test_gap_fills_zeros(self) -> None:
        scorer = AnomalyScorer(window=3, threshold=3.5, mad_floor=1.0, min_history=3)
        # Warm-up: buckets 0,1,2
        scorer.update(0, {"k": 10})
        scorer.update(1, {"k": 10})
        scorer.update(2, {"k": 10})
        # Gap from 2 to 5: buckets 3,4 filled with zero for k
        result = scorer.update(5, {"k": 0})
        # Not testing anomalies, just that history advanced by verifying len and next update
        assert len(scorer) == 1
        # The internal history should have zeros for buckets 3 and 4; we can
        # verify by checking that next count 10 is not anomalous (median 0)
        result = scorer.update(6, {"k": 10})
        # median of [0,0,10]? After gap and update5, history for window3 is [0,0,0];
        # update6 count10 leads median0, mad0, score=0.6745*10/1 > threshold => spike
        assert result and result[0].kind == "spike"

    def test_key_drop_to_zero_then_recover(self) -> None:
        scorer = AnomalyScorer(window=5, threshold=3.5, mad_floor=1.0, min_history=5)
        for bucket, count in enumerate([10, 12, 11, 13, 12]):
            scorer.update(bucket, {"k": count})
        drop_result = scorer.update(5, {"k": 0})
        assert drop_result and drop_result[0].kind == "drop"
        recover_result = scorer.update(6, {"k": 12})
        assert not recover_result

    def test_threshold_boundary_exact_spike(self) -> None:
        # median=0, mad_floor chosen so count=7 gives score exactly 3.5
        mad_floor = 0.6745 * 7 / 3.5
        scorer = AnomalyScorer(window=5, threshold=3.5, mad_floor=mad_floor, min_history=5)
        for bucket in range(5):
            scorer.update(bucket, {"k": 0})
        result = scorer.update(5, {"k": 7})
        assert len(result) == 1
        assert result[0].kind == "spike"
        assert result[0].score == pytest.approx(3.5)


class TestMaxKeysEviction:
    def test_eviction_event_and_len(self) -> None:
        events: list[dict[str, object]] = []
        scorer = AnomalyScorer(
            window=5,
            threshold=3.5,
            mad_floor=1.0,
            min_history=5,
            max_keys=2,
            on_event=events.append,
        )
        # Bucket 0: a and b both nonzero
        scorer.update(0, {"a": 1, "b": 1})
        # Buckets 1-4: a absent (zero), b nonzero
        for bucket in range(1, 5):
            scorer.update(bucket, {"b": 1})
        assert len(scorer) == 2
        # Adding c should evict a because a's last nonzero is oldest
        scorer.update(5, {"c": 1})
        assert len(scorer) == 2
        assert events == [{"event": "evicted", "key": "a"}]


class TestJsonRoundTrip:
    def test_round_trip_scores_identically(self) -> None:
        scorer = AnomalyScorer(window=5, threshold=3.5, mad_floor=1.0, min_history=5)
        for bucket, count in enumerate([10, 12, 11, 13, 12]):
            scorer.update(bucket, {"db_timeout": count})
        restored = AnomalyScorer.from_json(scorer.to_json())
        next_bucket = 5
        counts = {"db_timeout": 20}
        original_result = scorer.update(next_bucket, counts)
        restored_result = restored.update(next_bucket, counts)
        assert original_result == restored_result

    def test_input_too_large(self) -> None:
        with pytest.raises(AnomalyError) as exc_info:
            AnomalyScorer.from_json("x" * 10_000_001)
        assert exc_info.value.code == "input_too_large"

    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_state_rejected(self, literal: str) -> None:
        text = json.dumps(
            {
                "options": {
                    "window": 5,
                    "threshold": 3.5,
                    "mad_floor": 1.0,
                    "min_history": 5,
                    "max_keys": 10,
                },
                "histories": {},
            }
        ).replace("3.5", literal, 1)
        with pytest.raises(AnomalyError) as exc_info:
            AnomalyScorer.from_json(text)
        assert exc_info.value.code == "invalid_state"

    def test_invalid_state(self) -> None:
        with pytest.raises(AnomalyError) as exc_info:
            AnomalyScorer.from_json("not json")
        assert exc_info.value.code == "invalid_state"


class TestBucketize:
    def test_bucketize_example(self) -> None:
        events = [(0.5, "a"), (59.9, "a"), (60.0, "b")]
        assert bucketize(events, bucket_seconds=60) == {0: {"a": 2}, 1: {"b": 1}}

    def test_invalid_bucket_seconds(self) -> None:
        with pytest.raises(ValueError):
            bucketize([(0.0, "a")], 0)


class TestMain:
    def test_main_with_anomaly(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        counts_file = tmp_path / "counts.jsonl"
        lines = [
            json.dumps({"bucket": 0, "counts": {"db_timeout": 10}}),
            json.dumps({"bucket": 1, "counts": {"db_timeout": 12}}),
            json.dumps({"bucket": 2, "counts": {"db_timeout": 11}}),
            json.dumps({"bucket": 3, "counts": {"db_timeout": 13}}),
            json.dumps({"bucket": 4, "counts": {"db_timeout": 12}}),
            json.dumps({"bucket": 5, "counts": {"db_timeout": 20}}),
        ]
        counts_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        exit_code = main(["score", str(counts_file), "--window", "5", "--threshold", "3.5"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out.strip() == "5\tdb_timeout\tspike\t20\t5.396"
        assert captured.err == ""

    def test_main_no_anomaly(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        counts_file = tmp_path / "counts.jsonl"
        counts = [
            {"bucket": 0, "counts": {"a": 1}},
            {"bucket": 1, "counts": {"a": 1}},
            {"bucket": 2, "counts": {"a": 1}},
            {"bucket": 3, "counts": {"a": 1}},
            {"bucket": 4, "counts": {"a": 1}},
            {"bucket": 5, "counts": {"a": 1}},
        ]
        counts_file.write_text("\n".join(json.dumps(c) for c in counts) + "\n", encoding="utf-8")
        exit_code = main(["score", str(counts_file)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.out == ""

    def test_main_usage_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main([]) == 2
        captured = capsys.readouterr()
        assert "usage:" in captured.err

    def test_main_invalid_json_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad_file = tmp_path / "bad.jsonl"
        bad_file.write_text("not json\n", encoding="utf-8")
        assert main(["score", str(bad_file)]) == 2
        captured = capsys.readouterr()
        assert "invalid JSON" in captured.err

    def test_main_reads_sys_argv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["log-anomaly-score", "score"])
        assert main() == 2


class TestUpdateTypeErrors:
    def test_bucket_must_be_int(self) -> None:
        scorer = AnomalyScorer()
        with pytest.raises(TypeError):
            scorer.update(True, {"a": 1})

    def test_counts_must_be_mapping(self) -> None:
        scorer = AnomalyScorer()
        with pytest.raises(TypeError):
            scorer.update(0, [("a", 1)])

    def test_key_must_be_string(self) -> None:
        scorer = AnomalyScorer()
        with pytest.raises(AnomalyError) as exc_info:
            scorer.update(0, {1: 1})
        assert exc_info.value.code == "invalid_key"


def _valid_options() -> dict[str, object]:
    return {
        "window": 5,
        "threshold": 3.5,
        "mad_floor": 1.0,
        "min_history": 5,
        "max_keys": 10,
    }


class TestJsonValidation:
    def test_empty_state_is_valid(self) -> None:
        text = json.dumps({"options": _valid_options(), "histories": {}})
        scorer = AnomalyScorer.from_json(text)
        assert len(scorer) == 0
        assert scorer.update(0, {"a": 1}) == []

    @pytest.mark.parametrize(
        "payload",
        [
            "[]",
            "{}",
            json.dumps({"options": _valid_options(), "last_bucket": "x", "histories": {}}),
            json.dumps({"options": _valid_options(), "seen_buckets": -1, "histories": {}}),
            json.dumps({"options": _valid_options(), "histories": []}),
            json.dumps({"options": _valid_options(), "histories": {"k": "not-a-list"}}),
            json.dumps({"options": _valid_options(), "histories": {"k": [1, 2, 3, 4, 5, 6]}}),
            json.dumps({"options": _valid_options(), "histories": {"k": [True]}}),
            json.dumps({"options": _valid_options(), "histories": {"k": []}}),
            json.dumps(
                {
                    "options": {**_valid_options(), "max_keys": 1},
                    "histories": {"a": [1], "b": [1]},
                }
            ),
            json.dumps(
                {
                    "options": {**_valid_options(), "window": 2, "min_history": 3},
                    "histories": {},
                }
            ),
            json.dumps({"options": _valid_options(), "histories": {"x" * 513: []}}),
            json.dumps(
                {
                    "options": {**_valid_options(), "window": "5"},
                    "histories": {},
                }
            ),
            json.dumps(
                {
                    "options": {**_valid_options(), "threshold": "3.5"},
                    "histories": {},
                }
            ),
        ],
    )
    def test_invalid_state_shapes(self, payload: str) -> None:
        with pytest.raises(AnomalyError) as exc_info:
            AnomalyScorer.from_json(payload)
        assert exc_info.value.code == "invalid_state"


class TestMainErrorPaths:
    @pytest.mark.parametrize(
        "args",
        [
            ["score"],
            ["score", "counts.jsonl", "--window"],
            ["score", "counts.jsonl", "--window", "not-an-int"],
            ["score", "counts.jsonl", "--threshold"],
            ["score", "counts.jsonl", "--threshold", "not-a-float"],
            ["score", "counts.jsonl", "--bogus"],
            ["score", "counts.jsonl", "extra.jsonl"],
            ["score", "counts.jsonl", "--window", "2"],
        ],
    )
    def test_usage_errors(self, args: list[str]) -> None:
        assert main(args) == 2

    @pytest.mark.parametrize(
        "content",
        [
            "\n",
            "[]\n",
            json.dumps({"bucket": "0", "counts": {"a": 1}}) + "\n",
            json.dumps({"bucket": 0, "counts": []}) + "\n",
            json.dumps({"bucket": 0, "counts": {"a": -1}}) + "\n",
            json.dumps({"bucket": 1, "counts": {"a": 1}})
            + "\n"
            + json.dumps({"bucket": 0, "counts": {"a": 1}})
            + "\n",
        ],
    )
    def test_input_errors(self, tmp_path: Path, content: str) -> None:
        path = tmp_path / "counts.jsonl"
        path.write_text(content, encoding="utf-8")
        assert main(["score", str(path)]) == 2

    def test_missing_file(self, tmp_path: Path) -> None:
        assert main(["score", str(tmp_path / "missing.jsonl")]) == 2


class TestBoundedState:
    def test_initial_batch_respects_max_keys(self) -> None:
        events: list[dict[str, object]] = []
        scorer = AnomalyScorer(min_history=5, max_keys=1, on_event=events.append)
        scorer.update(0, {"a": 1, "b": 1})
        assert len(scorer) == 1
        assert events == [{"event": "evicted", "key": "a"}]
