from dataclasses import dataclass
from datetime import datetime


def _require_non_negative(**values: int) -> None:
    if any(value < 0 for value in values.values()):
        raise ValueError("counts must be non-negative")


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class EventTypeStats:
    event_type: str
    count: int
    oldest_ingested_at: datetime | None
    newest_ingested_at: datetime | None

    def __post_init__(self) -> None:
        _require_non_negative(count=self.count)
        if self.oldest_ingested_at is not None:
            _require_aware(self.oldest_ingested_at, "oldest_ingested_at")
        if self.newest_ingested_at is not None:
            _require_aware(self.newest_ingested_at, "newest_ingested_at")


@dataclass(frozen=True, slots=True)
class DataStatus:
    policy_version: int
    database_size_bytes: int
    event_count: int
    detection_count: int
    candidate_count: int
    incident_count: int
    protected_event_count: int
    event_types: tuple[EventTypeStats, ...]

    def __post_init__(self) -> None:
        _require_non_negative(
            database_size_bytes=self.database_size_bytes,
            event_count=self.event_count,
            detection_count=self.detection_count,
            candidate_count=self.candidate_count,
            incident_count=self.incident_count,
            protected_event_count=self.protected_event_count,
        )


@dataclass(frozen=True, slots=True)
class PruneRuleReport:
    event_type: str
    cutoff: datetime
    expired_events: int
    protected_events: int
    deletable_events: int
    deletable_detections: int

    def __post_init__(self) -> None:
        _require_aware(self.cutoff, "cutoff")
        _require_non_negative(
            expired_events=self.expired_events,
            protected_events=self.protected_events,
            deletable_events=self.deletable_events,
            deletable_detections=self.deletable_detections,
        )


@dataclass(frozen=True, slots=True)
class PruneReport:
    policy_version: int
    evaluation_time: datetime
    rules: tuple[PruneRuleReport, ...]

    def __post_init__(self) -> None:
        _require_aware(self.evaluation_time, "evaluation_time")

    @property
    def expired_events(self) -> int:
        return sum(rule.expired_events for rule in self.rules)

    @property
    def protected_events(self) -> int:
        return sum(rule.protected_events for rule in self.rules)

    @property
    def deletable_events(self) -> int:
        return sum(rule.deletable_events for rule in self.rules)

    @property
    def deletable_detections(self) -> int:
        return sum(rule.deletable_detections for rule in self.rules)
