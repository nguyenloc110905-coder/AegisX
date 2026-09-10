from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

TelemetryStatus = Literal["recent", "stale", "never", "disabled"]


@dataclass(frozen=True)
class DashboardCounts:
    devices: int
    events: int
    detections: int
    candidates: int
    open_incidents: int


@dataclass(frozen=True)
class DeviceRow:
    id: UUID
    name: str
    os: str
    os_version: str
    kernel: str
    architecture: str
    enrollment: Literal["enabled", "disabled"]
    telemetry_status: TelemetryStatus
    last_seen_at: datetime | None


@dataclass(frozen=True)
class EventRow:
    id: UUID
    timestamp: datetime
    event_type: str
    process_id: int | None
    executable: str | None
    local_ip: str | None
    local_port: int | None
    remote_ip: str | None
    remote_port: int | None
    severity: str


@dataclass(frozen=True)
class DetectionRow:
    id: UUID
    timestamp: datetime
    rule_id: str
    severity: str
    score: int
    reason: str


@dataclass(frozen=True)
class CandidateRow:
    id: UUID
    timestamp: datetime
    strategy_id: str
    confidence: str
    score: int
    reason: str


@dataclass(frozen=True)
class IncidentRow:
    id: UUID
    timestamp: datetime
    title: str
    severity: str
    risk_score: int
    status: str
    confidence: str
    disposition: str


@dataclass(frozen=True)
class DashboardSnapshot:
    counts: DashboardCounts
    devices: tuple[DeviceRow, ...]
    events: tuple[EventRow, ...]
    detections: tuple[DetectionRow, ...]
    candidates: tuple[CandidateRow, ...]
    incidents: tuple[IncidentRow, ...]
