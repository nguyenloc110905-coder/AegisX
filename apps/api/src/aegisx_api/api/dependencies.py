import secrets
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aegisx_api.models.device import Device
from aegisx_api.security import digest_device_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


async def get_current_device(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> Device:
    supplied_digest = digest_device_token(credentials.credentials if credentials else "")
    device = await session.scalar(
        select(Device).where(Device.token_digest == supplied_digest, Device.is_active.is_(True))
    )
    if device is None or not secrets.compare_digest(device.token_digest, supplied_digest):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_device_token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return device
