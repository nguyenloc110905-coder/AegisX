from aegisx_api.detection.registry import RuleRegistry
from aegisx_api.detection.types import DetectionResult
from aegisx_api.models.event import Event


class DetectionEngine:
    def __init__(self, registry: RuleRegistry) -> None:
        self._registry = registry

    def evaluate(self, event: Event) -> list[DetectionResult]:
        results: list[DetectionResult] = []
        for rule in self._registry.rules_for(event.event_type):
            match = rule.evaluate(event)
            if match is None:
                continue
            results.append(
                DetectionResult(
                    device_id=event.device_id,
                    source_event_id=event.id,
                    rule_id=rule.rule_id,
                    timestamp=event.timestamp,
                    severity=rule.severity,
                    score_contribution=rule.score_contribution,
                    reason=match.reason,
                    evidence_event_ids=match.evidence_event_ids,
                )
            )
        return results
