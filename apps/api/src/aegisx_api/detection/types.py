from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

type DetectionSeverity = Literal["informational", "low", "medium", "high", "critical"]


@dataclass(frozen=True)
class RuleMatch:
    reason: str
    evidence_event_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class DetectionResult:
    device_id: UUID
    source_event_id: UUID
    rule_id: str
    timestamp: datetime
    severity: DetectionSeverity
    score_contribution: int
    reason: str
    evidence_event_ids: tuple[UUID, ...]
