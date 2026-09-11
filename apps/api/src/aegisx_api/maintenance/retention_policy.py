from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

RETENTION_POLICY_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class RetentionRule:
    event_type: str
    retention: timedelta

    def __post_init__(self) -> None:
        if not self.event_type:
            raise ValueError("event_type must not be empty")
        if self.retention <= timedelta(0):
            raise ValueError("retention must be positive")


RETENTION_RULES: Final = (
    RetentionRule("process.resource_usage", timedelta(hours=24)),
    RetentionRule("network.listener_observed", timedelta(hours=24)),
    RetentionRule("network.connection_observed", timedelta(hours=24)),
    RetentionRule("system.status", timedelta(days=7)),
    RetentionRule("process.started", timedelta(days=30)),
    RetentionRule("process.exited", timedelta(days=30)),
    RetentionRule("network.listener_opened", timedelta(days=30)),
    RetentionRule("network.listener_closed", timedelta(days=30)),
    RetentionRule("network.connection_opened", timedelta(days=30)),
    RetentionRule("network.connection_closed", timedelta(days=30)),
)


def cutoff_for(rule: RetentionRule, evaluation_time: datetime) -> datetime:
    if evaluation_time.tzinfo is None or evaluation_time.utcoffset() is None:
        raise ValueError("evaluation_time must be timezone-aware")
    return evaluation_time - rule.retention
