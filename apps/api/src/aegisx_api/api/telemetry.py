from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from aegisx_api.api.dependencies import get_current_device, get_database_session
from aegisx_api.models.device import Device
from aegisx_api.schemas.event import EventBatchRequest, EventBatchResponse
from aegisx_api.services.telemetry_ingestion import TelemetryIngestionService

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.post(
    "/events",
    response_model=EventBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_events(
    payload: EventBatchRequest,
    request: Request,
    device: Annotated[Device, Depends(get_current_device)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> EventBatchResponse:
    batch_limit = request.app.state.settings.telemetry_batch_limit
    if len(payload.events) > batch_limit:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "telemetry_batch_too_large", "limit": batch_limit},
        )
    ingestion_service = cast(
        TelemetryIngestionService, request.app.state.telemetry_ingestion_service
    )
    return await ingestion_service.ingest(session, device, payload.events)
