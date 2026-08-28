from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Observation(BaseModel):
    event_type: str
    source: str
    data: dict[str, Any]
    severity_hint: Literal["normal", "low", "medium", "high"] = "normal"
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class NormalizedEvent(BaseModel):
    id: str
    schema_version: Literal[1] = 1
    timestamp: datetime
    event_type: str
    source: str
    severity_hint: Literal["normal", "low", "medium", "high"]
    data: dict[str, Any]
    metadata: dict[str, str | int | float | bool | None]


def normalize_observation(observation: Observation) -> NormalizedEvent:
    return NormalizedEvent(
        id=str(uuid4()),
        timestamp=datetime.now(UTC),
        **observation.model_dump(),
    )
