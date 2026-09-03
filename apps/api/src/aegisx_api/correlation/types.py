from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

type CorrelationConfidence = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class CorrelationResult:
    correlation_key: str
    device_id: UUID
    strategy_id: str
    start_timestamp: datetime
    end_timestamp: datetime
    confidence: CorrelationConfidence
    aggregate_score: int
    detection_ids: tuple[UUID, ...]
    event_ids: tuple[UUID, ...]
