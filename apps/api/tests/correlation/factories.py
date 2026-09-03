from datetime import UTC, datetime
from uuid import UUID, uuid4

from aegisx_api.models.detection import Detection
from aegisx_api.models.event import Event


def event(
    *,
    event_type: str,
    device_id: UUID,
    timestamp: datetime,
    data: dict[str, object],
    event_id: UUID | None = None,
) -> Event:
    return Event(
        id=event_id or uuid4(),
        device_id=device_id,
        schema_version=1,
        timestamp=timestamp.astimezone(UTC),
        event_type=event_type,
        source="test",
        severity_hint="normal",
        data=data,
        metadata_={},
    )


def detection(
    *,
    rule_id: str,
    source_event: Event,
    score_contribution: int,
    detection_id: UUID | None = None,
) -> Detection:
    return Detection(
        id=detection_id or uuid4(),
        device_id=source_event.device_id,
        source_event_id=source_event.id,
        source_event=source_event,
        rule_id=rule_id,
        timestamp=source_event.timestamp,
        severity="low",
        score_contribution=score_contribution,
        reason="test evidence",
        evidence_event_ids=[str(source_event.id)],
    )
