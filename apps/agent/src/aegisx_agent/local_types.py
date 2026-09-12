from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EventPriority(StrEnum):
    BULK = "BULK"
    OPERATIONAL = "OPERATIONAL"
    SECURITY = "SECURITY"
    UNCLASSIFIED = "UNCLASSIFIED"


class DeliveryState(StrEnum):
    PENDING = "PENDING"
    ACKED = "ACKED"
    QUARANTINED = "QUARANTINED"


class CoverageGapCategory(StrEnum):
    STORAGE_LIMIT = "STORAGE_LIMIT"
    STORAGE_WRITE_FAILURE = "STORAGE_WRITE_FAILURE"
    CLOCK_REGRESSION = "CLOCK_REGRESSION"
    LEGACY_MIGRATION_FAILURE = "LEGACY_MIGRATION_FAILURE"


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _require_non_negative(**values: int) -> None:
    if any(value < 0 for value in values.values()):
        raise ValueError("counts and sizes must be non-negative")


@dataclass(frozen=True, slots=True)
class LocalEventTypeStats:
    event_type: str
    count: int
    payload_bytes: int
    oldest_recorded_at: datetime
    newest_recorded_at: datetime

    def __post_init__(self) -> None:
        _require_non_negative(count=self.count, payload_bytes=self.payload_bytes)
        _require_aware(self.oldest_recorded_at, "oldest_recorded_at")
        _require_aware(self.newest_recorded_at, "newest_recorded_at")


@dataclass(frozen=True, slots=True)
class LocalDataStatus:
    policy_version: int
    schema_version: int
    logical_payload_bytes: int
    database_file_bytes: int
    event_count: int
    pending_count: int
    acknowledged_count: int
    quarantined_count: int
    coverage_gap_count: int
    event_types: tuple[LocalEventTypeStats, ...]

    def __post_init__(self) -> None:
        _require_non_negative(
            logical_payload_bytes=self.logical_payload_bytes,
            database_file_bytes=self.database_file_bytes,
            event_count=self.event_count,
            pending_count=self.pending_count,
            acknowledged_count=self.acknowledged_count,
            quarantined_count=self.quarantined_count,
            coverage_gap_count=self.coverage_gap_count,
        )


@dataclass(frozen=True, slots=True)
class LocalVerifyResult:
    valid: bool
    checked_events: int
    first_bad_sequence: int | None
    failure_category: str | None

    def __post_init__(self) -> None:
        _require_non_negative(checked_events=self.checked_events)


@dataclass(frozen=True, slots=True)
class LocalPruneRuleReport:
    priority: EventPriority
    cutoff: datetime
    eligible_events: int
    eligible_payload_bytes: int

    def __post_init__(self) -> None:
        _require_aware(self.cutoff, "cutoff")
        _require_non_negative(
            eligible_events=self.eligible_events,
            eligible_payload_bytes=self.eligible_payload_bytes,
        )


@dataclass(frozen=True, slots=True)
class LocalPruneReport:
    policy_version: int
    evaluation_time: datetime
    rules: tuple[LocalPruneRuleReport, ...]

    def __post_init__(self) -> None:
        _require_aware(self.evaluation_time, "evaluation_time")

    @property
    def eligible_events(self) -> int:
        return sum(rule.eligible_events for rule in self.rules)

    @property
    def eligible_payload_bytes(self) -> int:
        return sum(rule.eligible_payload_bytes for rule in self.rules)


@dataclass(frozen=True, slots=True)
class LocalPruneResult:
    policy_version: int
    evaluation_time: datetime
    deleted_events: int
    deleted_payload_bytes: int
    completed: bool

    def __post_init__(self) -> None:
        _require_aware(self.evaluation_time, "evaluation_time")
        _require_non_negative(
            deleted_events=self.deleted_events,
            deleted_payload_bytes=self.deleted_payload_bytes,
        )
