from typing import Any

import httpx
from pydantic import BaseModel, Field

from aegisx_agent.credentials import AgentCredentials
from aegisx_agent.events import NormalizedEvent


class DeliveryError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"telemetry delivery failed with HTTP {status_code}")


class TransientDeliveryError(DeliveryError):
    pass


class PermanentDeliveryError(DeliveryError):
    pass


class DeviceProfile(BaseModel):
    external_id: str
    name: str
    os: str = "Linux"
    os_version: str
    kernel: str
    architecture: str


class IngestionResult(BaseModel):
    accepted: int = Field(ge=0)
    duplicates: int = Field(ge=0)


class AegisXClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )

    async def register(self, profile: DeviceProfile) -> AgentCredentials:
        response = await self._client.post(
            "/api/v1/devices/register",
            json=profile.model_dump(),
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return AgentCredentials(device_id=str(payload["device"]["id"]), token=payload["token"])

    async def send_events(
        self,
        token: str,
        events: list[NormalizedEvent],
    ) -> IngestionResult:
        response = await self._client.post(
            "/api/v1/telemetry/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"events": [event.model_dump(mode="json") for event in events]},
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientDeliveryError(response.status_code)
        if response.is_error:
            raise PermanentDeliveryError(response.status_code)
        return IngestionResult.model_validate(response.json())

    async def close(self) -> None:
        await self._client.aclose()
