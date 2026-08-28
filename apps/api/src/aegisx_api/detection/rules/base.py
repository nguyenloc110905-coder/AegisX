from typing import Protocol

from aegisx_api.detection.types import DetectionSeverity, RuleMatch
from aegisx_api.models.event import Event


class DetectionRule(Protocol):
    rule_id: str
    name: str
    description: str
    category: str
    severity: DetectionSeverity
    score_contribution: int
    event_types: frozenset[str]

    def evaluate(self, event: Event) -> RuleMatch | None: ...
