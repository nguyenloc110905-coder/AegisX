from dataclasses import dataclass

import pytest

from aegisx_api.detection.engine import DetectionEngine
from aegisx_api.detection.registry import RuleRegistry
from aegisx_api.detection.types import RuleMatch

from .test_rules import event


@dataclass(frozen=True)
class FakeRule:
    rule_id: str
    name: str = "Fake rule"
    description: str = "For engine tests"
    category: str = "test"
    severity: str = "low"
    score_contribution: int = 7
    event_types: frozenset[str] = frozenset({"system.status"})
    matches: bool = True

    def evaluate(self, source_event):
        if not self.matches:
            return None
        return RuleMatch(reason=self.rule_id, evidence_event_ids=(source_event.id,))


def test_registry_indexes_rules_and_rejects_duplicate_ids() -> None:
    first = FakeRule("FIRST")
    second = FakeRule("SECOND", event_types=frozenset({"process.started"}))
    registry = RuleRegistry([first, second])

    assert registry.rules_for("system.status") == (first,)
    assert registry.rules_for("unknown") == ()
    with pytest.raises(ValueError, match="duplicate rule ID: FIRST"):
        RuleRegistry([first, FakeRule("FIRST")])


def test_engine_returns_results_only_for_matching_relevant_rules() -> None:
    source = event("system.status", {"hostname": "test"})
    engine = DetectionEngine(RuleRegistry([FakeRule("MATCH"), FakeRule("NO_MATCH", matches=False)]))

    results = engine.evaluate(source)

    assert len(results) == 1
    assert results[0].rule_id == "MATCH"
    assert results[0].device_id == source.device_id
    assert results[0].source_event_id == source.id
    assert results[0].timestamp == source.timestamp
    assert results[0].severity == "low"
    assert results[0].score_contribution == 7
    assert results[0].evidence_event_ids == (source.id,)


def test_engine_returns_no_results_for_event_without_registered_rules() -> None:
    assert DetectionEngine(RuleRegistry([])).evaluate(event("system.status", {})) == []
