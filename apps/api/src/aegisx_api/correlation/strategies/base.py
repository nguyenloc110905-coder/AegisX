from collections.abc import Sequence
from datetime import timedelta
from typing import Protocol

from aegisx_api.correlation.types import CorrelationResult
from aegisx_api.models.detection import Detection


class CorrelationStrategy(Protocol):
    strategy_id: str
    name: str
    description: str
    required_rule_ids: frozenset[str]

    def evaluate(
        self, evidence: Sequence[Detection], window: timedelta
    ) -> tuple[CorrelationResult, ...]: ...
