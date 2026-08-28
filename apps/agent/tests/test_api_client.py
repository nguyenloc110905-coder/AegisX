import json
import stat
from pathlib import Path

import httpx
import pytest

from aegisx_agent.api_client import (
    AegisXClient,
    DeviceProfile,
    PermanentDeliveryError,
    TransientDeliveryError,
)
from aegisx_agent.collectors.system import SystemCollector
from aegisx_agent.credentials import AgentCredentials, load_credentials, save_credentials
from aegisx_agent.events import normalize_observation


def test_credentials_round_trip_with_private_permissions(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    credentials = AgentCredentials(device_id="device-uuid", token="super-secret-token")

    save_credentials(path, credentials)

    assert load_credentials(path) == credentials
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_client_registers_and_sends_events_without_leaking_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/devices/register"):
            return httpx.Response(
                201,
                json={
                    "device": {"id": "device-uuid", "external_id": "external-uuid"},
                    "token": "super-secret-token",
                },
            )
        assert request.headers["Authorization"] == "Bearer super-secret-token"
        body = json.loads(request.content)
        assert body["events"][0]["event_type"] == "system.status"
        return httpx.Response(202, json={"accepted": 1, "duplicates": 0})

    client = AegisXClient(
        base_url="http://aegisx.test",
        transport=httpx.MockTransport(handler),
    )
    profile = DeviceProfile(
        external_id="external-uuid",
        name="Fedora Laptop",
        os="Linux",
        os_version="Fedora 42",
        kernel="6.15.9",
        architecture="x86_64",
    )

    credentials = await client.register(profile)
    event = normalize_observation(SystemCollector().collect())
    result = await client.send_events(credentials.token, [event])
    await client.close()

    assert credentials == AgentCredentials(device_id="device-uuid", token="super-secret-token")
    assert result.accepted == 1
    assert result.duplicates == 0
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (400, PermanentDeliveryError),
        (401, PermanentDeliveryError),
        (422, PermanentDeliveryError),
        (429, TransientDeliveryError),
        (500, TransientDeliveryError),
        (503, TransientDeliveryError),
    ],
)
async def test_client_classifies_ingestion_http_errors(status_code: int, error_type: type) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code, request=request))
    client = AegisXClient(base_url="http://aegisx.test", transport=transport)
    event = normalize_observation(SystemCollector().collect())

    with pytest.raises(error_type):
        await client.send_events("secret-token", [event])

    await client.close()
