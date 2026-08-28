from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ProcessStartedData(BaseModel):
    pid: int = Field(gt=0)
    ppid: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=256)
    executable: str | None = Field(default=None, max_length=4096)
    user: str | None = Field(default=None, max_length=256)
    command_line: list[str] = Field(default_factory=list, max_length=256)
    started_at: datetime | None = None


class ProcessResourceUsageData(BaseModel):
    pid: int = Field(gt=0)
    cpu_percent: float = Field(ge=0)
    memory_bytes: int = Field(ge=0)


class SystemStatusData(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    os: str = Field(min_length=1, max_length=64)
    kernel: str = Field(min_length=1, max_length=128)
    uptime_seconds: float = Field(ge=0)
    cpu_count: int = Field(gt=0)
    memory_total_bytes: int = Field(gt=0)


class EventEnvelope(BaseModel):
    id: UUID
    schema_version: Literal[1]
    timestamp: datetime
    source: str = Field(min_length=1, max_length=64)
    severity_hint: Literal["normal", "low", "medium", "high"] = "normal"
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ProcessStartedEvent(EventEnvelope):
    event_type: Literal["process.started"]
    data: ProcessStartedData


class ProcessResourceUsageEvent(EventEnvelope):
    event_type: Literal["process.resource_usage"]
    data: ProcessResourceUsageData


class SystemStatusEvent(EventEnvelope):
    event_type: Literal["system.status"]
    data: SystemStatusData


TelemetryEvent = Annotated[
    ProcessStartedEvent | ProcessResourceUsageEvent | SystemStatusEvent,
    Field(discriminator="event_type"),
]


class EventBatchRequest(BaseModel):
    events: list[TelemetryEvent] = Field(min_length=1, max_length=100)


class EventBatchResponse(BaseModel):
    accepted: int
    duplicates: int
