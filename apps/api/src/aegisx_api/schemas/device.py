from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DeviceRegistrationRequest(BaseModel):
    external_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    name: str = Field(min_length=1, max_length=128)
    os: Literal["Linux"]
    os_version: str = Field(min_length=1, max_length=128)
    kernel: str = Field(min_length=1, max_length=128)
    architecture: str = Field(min_length=1, max_length=64)


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_id: str
    name: str
    os: str
    os_version: str
    kernel: str
    architecture: str
    is_active: bool
    created_at: datetime


class DeviceRegistrationResponse(BaseModel):
    device: DeviceResponse
    token: str
