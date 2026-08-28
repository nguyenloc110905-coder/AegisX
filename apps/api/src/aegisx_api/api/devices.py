from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aegisx_api.api.dependencies import get_database_session
from aegisx_api.models.device import Device
from aegisx_api.schemas.device import (
    DeviceRegistrationRequest,
    DeviceRegistrationResponse,
    DeviceResponse,
)
from aegisx_api.security import digest_device_token, generate_device_token

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post(
    "/register",
    response_model=DeviceRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_device(
    payload: DeviceRegistrationRequest,
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> DeviceRegistrationResponse:
    token = generate_device_token()
    device = Device(
        **payload.model_dump(),
        token_digest=digest_device_token(token),
    )
    session.add(device)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "device_already_registered"},
        ) from error
    await session.refresh(device)
    return DeviceRegistrationResponse(device=DeviceResponse.model_validate(device), token=token)
