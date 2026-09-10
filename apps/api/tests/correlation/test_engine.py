from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest

from aegisx_api.correlation.defaults import create_default_correlation_engine
from aegisx_api.correlation.engine import CorrelationEngine
from aegisx_api.correlation.registry import CorrelationRegistry
from aegisx_api.correlation.types import CorrelationResult

from .factories import detection, event
from .test_process_listener_activity import (
    DEVICE_ID,
    LISTENER_TIMESTAMP,
    PROCESS_TIMESTAMP,
    listener_detection,
    process_detection,
)


@dataclass(frozen=True)
class FakeStrategy:
    strategy_id: str
    required_rule_ids: frozenset[str]
    result: CorrelationResult | None = None
    name: str = "Fake strategy"
    description: str = "Strategy test double"

    def evaluate(self, evidence, window):
        del evidence, window
        return () if self.result is None else (self.result,)


def result(strategy_id: str = "FIRST") -> CorrelationResult:
    return CorrelationResult(
        correlation_key="a" * 64,
        device_id=DEVICE_ID,
        strategy_id=strategy_id,
        start_timestamp=PROCESS_TIMESTAMP,
        end_timestamp=LISTENER_TIMESTAMP,
        confidence="low",
        aggregate_score=5,
        detection_ids=(UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),),
        event_ids=(UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),),
    )


def test_registry_indexes_strategies_by_required_rule_id_and_rejects_duplicates() -> None:
    first = FakeStrategy("FIRST", frozenset({"PROCESS_STARTED", "LISTENER_OPENED"}))
    second = FakeStrategy("SECOND", frozenset({"OTHER"}))
    registry = CorrelationRegistry([first, second])

    assert registry.strategies_for(frozenset({"PROCESS_STARTED"})) == (first,)
    assert registry.strategies_for(frozenset({"PROCESS_STARTED", "OTHER"})) == (first, second)
    assert registry.strategies_for(frozenset({"UNKNOWN"})) == ()
    with pytest.raises(ValueError, match="duplicate strategy ID: FIRST"):
        CorrelationRegistry([first, FakeStrategy("FIRST", frozenset({"OTHER"}))])


def test_engine_returns_no_result_when_new_detections_do_not_match_a_strategy() -> None:
    irrelevant_event = event(
        event_type="system.status",
        device_id=DEVICE_ID,
        timestamp=LISTENER_TIMESTAMP,
        data={},
    )
    irrelevant = detection(
        rule_id="IRRELEVANT",
        source_event=irrelevant_event,
        score_contribution=0,
    )

    assert (
        create_default_correlation_engine().evaluate(
            (irrelevant,), (process_detection(), listener_detection()), timedelta(minutes=5)
        )
        == ()
    )


def test_engine_deduplicates_results_by_stable_correlation_key() -> None:
    first = FakeStrategy("FIRST", frozenset({"PROCESS_STARTED"}), result())
    second = FakeStrategy("SECOND", frozenset({"LISTENER_OPENED"}), result("SECOND"))
    engine = CorrelationEngine(CorrelationRegistry([first, second]))

    results = engine.evaluate(
        (process_detection(), listener_detection()),
        (process_detection(), listener_detection()),
        timedelta(minutes=5),
    )

    assert results == (result(),)


def test_engine_collapses_repeated_listener_transitions_for_one_process_identity() -> None:
    first_listener = listener_detection()
    repeated_listener = listener_detection(
        timestamp=LISTENER_TIMESTAMP + timedelta(seconds=10),
        event_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        detection_id=UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
    )
    engine = create_default_correlation_engine()

    results = engine.evaluate(
        (first_listener, repeated_listener),
        (process_detection(), first_listener, repeated_listener),
        timedelta(minutes=5),
    )

    assert len(results) == 1
    assert results[0].end_timestamp == LISTENER_TIMESTAMP
    assert results[0].aggregate_score == 5
