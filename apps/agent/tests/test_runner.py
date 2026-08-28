from pathlib import Path

import httpx
import pytest

from aegisx_agent.api_client import DeviceProfile, IngestionResult, PermanentDeliveryError
from aegisx_agent.config import AgentSettings
from aegisx_agent.credentials import AgentCredentials
from aegisx_agent.events import Observation
from aegisx_agent.runner import collect_once


class FakeCollector:
    def collect(self) -> Observation:
        return Observation(
            event_type="system.status",
            source="test",
            data={
                "hostname": "test",
                "os": "Linux",
                "kernel": "test",
                "uptime_seconds": 1,
                "cpu_count": 1,
                "memory_total_bytes": 1,
            },
        )


class FakeClient:
    def __init__(self) -> None:
        self.registered = 0
        self.sent = 0
        self.fail_delivery = False
        self.permanent_failure = False

    async def register(self, profile: DeviceProfile) -> AgentCredentials:
        self.registered += 1
        return AgentCredentials(device_id="device-id", token="test-token")

    async def send_events(self, token: str, events) -> IngestionResult:
        assert token == "test-token"
        if self.fail_delivery:
            raise httpx.ConnectError("API offline")
        if self.permanent_failure:
            raise PermanentDeliveryError(422)
        self.sent += len(events)
        return IngestionResult(accepted=len(events), duplicates=0)


@pytest.mark.asyncio
async def test_collect_once_registers_persists_and_sends(tmp_path: Path) -> None:
    settings = AgentSettings(
        _env_file=None,
        state_directory=tmp_path,
        api_url="http://test",
    )
    client = FakeClient()

    result = await collect_once(settings, client=client, collectors=[FakeCollector()])

    assert result.accepted == 1
    assert result.queued == 0
    assert result.delivery_status == "delivered"
    assert client.registered == 1
    assert client.sent == 1
    assert (tmp_path / "identity.json").exists()
    assert (tmp_path / "credentials.json").exists()

    await collect_once(settings, client=client, collectors=[FakeCollector()])
    assert client.registered == 1


@pytest.mark.asyncio
async def test_collect_once_retains_offline_events_and_flushes_later(tmp_path: Path) -> None:
    settings = AgentSettings(
        _env_file=None,
        state_directory=tmp_path,
        api_url="http://test",
        max_outbox_events=100,
    )
    client = FakeClient()
    client.fail_delivery = True

    offline = await collect_once(settings, client=client, collectors=[FakeCollector()])

    assert offline.delivery_status == "deferred"
    assert offline.queued == 1

    client.fail_delivery = False
    recovered = await collect_once(settings, client=client, collectors=[FakeCollector()])

    assert recovered.delivery_status == "delivered"
    assert recovered.accepted == 2
    assert recovered.queued == 0


@pytest.mark.asyncio
async def test_collect_once_quarantines_permanently_invalid_event(tmp_path: Path) -> None:
    settings = AgentSettings(
        _env_file=None,
        state_directory=tmp_path,
        api_url="http://test",
        max_outbox_events=100,
    )
    client = FakeClient()
    client.permanent_failure = True

    result = await collect_once(settings, client=client, collectors=[FakeCollector()])

    assert result.delivery_status == "delivered"
    assert result.queued == 0
    assert result.quarantined == 1
