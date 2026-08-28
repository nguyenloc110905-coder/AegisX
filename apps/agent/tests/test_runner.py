from pathlib import Path

import pytest

from aegisx_agent.api_client import DeviceProfile, IngestionResult
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

    async def register(self, profile: DeviceProfile) -> AgentCredentials:
        self.registered += 1
        return AgentCredentials(device_id="device-id", token="test-token")

    async def send_events(self, token: str, events) -> IngestionResult:
        assert token == "test-token"
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
    assert client.registered == 1
    assert client.sent == 1
    assert (tmp_path / "identity.json").exists()
    assert (tmp_path / "credentials.json").exists()

    await collect_once(settings, client=client, collectors=[FakeCollector()])
    assert client.registered == 1
