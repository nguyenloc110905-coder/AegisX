from collections.abc import Sequence
from datetime import timedelta

from aegisx_api.correlation.registry import CorrelationRegistry
from aegisx_api.correlation.types import CorrelationResult
from aegisx_api.models.detection import Detection


class CorrelationEngine:
    def __init__(self, registry: CorrelationRegistry) -> None:
        self._registry = registry

    def evaluate(
        self,
        new_detections: Sequence[Detection],
        evidence: Sequence[Detection],
        window: timedelta,
    ) -> tuple[CorrelationResult, ...]:
        new_rule_ids = frozenset(detection.rule_id for detection in new_detections)
        results_by_key: dict[str, CorrelationResult] = {}
        for strategy in self._registry.strategies_for(new_rule_ids):
            for result in strategy.evaluate(evidence, window):
                results_by_key.setdefault(result.correlation_key, result)
        return tuple(results_by_key[key] for key in sorted(results_by_key))

    def strategy_ids_for(self, new_detections: Sequence[Detection]) -> tuple[str, ...]:
        rule_ids = frozenset(detection.rule_id for detection in new_detections)
        return tuple(strategy.strategy_id for strategy in self._registry.strategies_for(rule_ids))
