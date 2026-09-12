import hashlib
import json
from datetime import timedelta
from typing import Final

from aegisx_agent.events import NormalizedEvent
from aegisx_agent.local_types import DeliveryState, EventPriority

LOCAL_POLICY_VERSION: Final = 1

EVENT_PRIORITIES: Final = {
    "process.resource_usage": EventPriority.BULK,
    "network.listener_observed": EventPriority.BULK,
    "network.connection_observed": EventPriority.BULK,
    "system.status": EventPriority.OPERATIONAL,
    "process.started": EventPriority.SECURITY,
    "process.exited": EventPriority.SECURITY,
    "network.listener_opened": EventPriority.SECURITY,
    "network.listener_closed": EventPriority.SECURITY,
    "network.connection_opened": EventPriority.SECURITY,
    "network.connection_closed": EventPriority.SECURITY,
}

RETENTION_BY_PRIORITY: Final = {
    EventPriority.BULK: timedelta(hours=24),
    EventPriority.OPERATIONAL: timedelta(days=7),
    EventPriority.SECURITY: timedelta(days=30),
}


def classify_event(event_type: str) -> EventPriority:
    return EVENT_PRIORITIES.get(event_type, EventPriority.UNCLASSIFIED)


def retention_for(priority: EventPriority) -> timedelta | None:
    return RETENTION_BY_PRIORITY.get(priority)


def canonical_event_json(event: NormalizedEvent) -> str:
    return json.dumps(
        event.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def calculate_payload_hash(canonical_payload: str) -> str:
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


__all__ = [
    "LOCAL_POLICY_VERSION",
    "DeliveryState",
    "EventPriority",
    "calculate_payload_hash",
    "canonical_event_json",
    "classify_event",
    "retention_for",
]
