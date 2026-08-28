from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aegisx_api.api.dependencies import get_current_device, get_database_session
from aegisx_api.models.device import Device
from aegisx_api.models.event import Event
from aegisx_api.schemas.event import EventBatchRequest, EventBatchResponse

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.post(
    "/events",
    response_model=EventBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_events(
    payload: EventBatchRequest,
    device: Annotated[Device, Depends(get_current_device)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> EventBatchResponse:
    event_ids = [event.id for event in payload.events]
    existing_ids = set(
        (await session.scalars(select(Event.id).where(Event.id.in_(event_ids)))).all()
    )
    seen_ids = set(existing_ids)
    accepted = 0
    duplicates = len(existing_ids)

    for envelope in payload.events:
        if envelope.id in seen_ids:
            if envelope.id not in existing_ids:
                duplicates += 1
            continue
        seen_ids.add(envelope.id)
        data = envelope.data.model_dump(mode="json")
        session.add(
            Event(
                id=envelope.id,
                device_id=device.id,
                schema_version=envelope.schema_version,
                timestamp=envelope.timestamp,
                event_type=envelope.event_type,
                source=envelope.source,
                severity_hint=envelope.severity_hint,
                data=data,
                metadata_=envelope.metadata,
                process_id=data.get("pid"),
                parent_process_id=data.get("ppid"),
                executable=data.get("executable"),
            )
        )
        accepted += 1

    device.last_seen_at = datetime.now(UTC)
    await session.commit()
    return EventBatchResponse(accepted=accepted, duplicates=duplicates)
