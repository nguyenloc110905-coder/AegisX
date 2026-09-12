import sqlite3
from pathlib import Path

import httpx
import pytest

from aegisx_agent.api_client import DeviceProfile, IngestionResult, PermanentDeliveryError
from aegisx_agent.config import AgentSettings
from aegisx_agent.credentials import AgentCredentials
from aegisx_agent.events import Observation, normalize_observation
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
    def __init__(self, journal_path: Path | None = None) -> None:
        self.registered = 0
        self.sent = 0
        self.fail_delivery = False
        self.permanent_failure = False
        self.journal_path = journal_path

    async def register(self, profile: DeviceProfile) -> AgentCredentials:
        self.registered += 1
        return AgentCredentials(device_id="device-id", token="test-token")

    async def send_events(self, token: str, events) -> IngestionResult:
        assert token == "test-token"
        if self.journal_path is not None:
            with sqlite3.connect(self.journal_path) as connection:
                state = connection.execute(
                    "SELECT delivery_state FROM local_events WHERE event_id = ?",
                    (events[0].id,),
                ).fetchone()
            assert state == ("PENDING",)
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
    client = FakeClient(tmp_path / "outbox.sqlite3")

    result = await collect_once(settings, client=client, collectors=[FakeCollector()])

    assert result.accepted == 1
    assert result.queued == 0
    assert result.delivery_status == "delivered"
    assert result.coverage_status == "complete"
    assert client.registered == 1
    assert client.sent == 1
    assert (tmp_path / "identity.json").exists()
    assert (tmp_path / "credentials.json").exists()
    with sqlite3.connect(tmp_path / "outbox.sqlite3") as connection:
        assert connection.execute("SELECT delivery_state FROM local_events").fetchone() == (
            "ACKED",
        )

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
    assert offline.coverage_status == "complete"
    assert offline.queued == 1

    client.fail_delivery = False
    recovered = await collect_once(settings, client=client, collectors=[FakeCollector()])

    assert recovered.delivery_status == "delivered"
    assert recovered.coverage_status == "complete"
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
    assert result.coverage_status == "complete"
    assert result.queued == 0
    assert result.quarantined == 1
    with sqlite3.connect(tmp_path / "outbox.sqlite3") as connection:
        assert connection.execute("SELECT delivery_state FROM local_events").fetchone() == (
            "QUARANTINED",
        )


@pytest.mark.asyncio
async def test_collect_once_does_not_send_when_local_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AgentSettings(
        _env_file=None,
        state_directory=tmp_path,
        api_url="http://test",
    )
    client = FakeClient()

    class FailedStore:
        delivery_only = False

        async def enqueue(self, events) -> int:
            from aegisx_agent.local_store import LocalStoreCapacityError

            raise LocalStoreCapacityError("test capacity")

        async def count(self) -> int:
            return 0

        async def close(self) -> None:
            return None

    async def failed_open(*args, **kwargs):
        return FailedStore()

    monkeypatch.setattr("aegisx_agent.runner.AsyncLocalTelemetryStore.open", failed_open)

    result = await collect_once(settings, client=client, collectors=[FakeCollector()])

    assert result.delivery_status == "deferred"
    assert result.coverage_status == "degraded"
    assert result.accepted == 0
    assert result.queued == 0
    assert client.registered == 0
    assert client.sent == 0


@pytest.mark.asyncio
async def test_collect_once_flushes_failed_migration_in_delivery_only_mode(
    tmp_path: Path,
) -> None:
    path = tmp_path / "outbox.sqlite3"
    pending = Observation(
        event_type="system.status",
        source="legacy-test",
        data={"hostname": "legacy"},
    )
    normalized = normalize_observation(pending)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE pending_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE quarantined_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, reason TEXT NOT NULL, "
            "quarantined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO pending_events (event_id, payload) VALUES (?, ?)",
            (normalized.id, normalized.model_dump_json()),
        )
        connection.execute(
            "INSERT INTO quarantined_events (event_id, payload, reason) VALUES (?, ?, ?)",
            ("00000000-0000-0000-0000-000000000099", "{", "http_422"),
        )

    class MustNotCollect:
        def collect(self) -> Observation:
            raise AssertionError("delivery-only fallback must not collect new telemetry")

    settings = AgentSettings(
        _env_file=None,
        state_directory=tmp_path,
        api_url="http://test",
    )
    client = FakeClient()

    result = await collect_once(settings, client=client, collectors=[MustNotCollect()])

    assert result.coverage_status == "degraded"
    assert result.delivery_status == "delivered"
    assert result.accepted == 1
    assert result.queued == 0
    assert client.sent == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)


@pytest.mark.asyncio
async def test_collect_once_propagates_observation_settings_to_default_collectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AgentSettings(
        _env_file=None,
        state_directory=tmp_path,
        api_url="http://test",
        emit_process_resource_usage=True,
        emit_network_snapshot_observations=True,
    )
    constructor_arguments: dict[str, dict[str, object]] = {}

    def process_collector(**kwargs: object) -> FakeCollector:
        constructor_arguments["process"] = kwargs
        return FakeCollector()

    def network_collector(**kwargs: object) -> FakeCollector:
        constructor_arguments["network"] = kwargs
        return FakeCollector()

    monkeypatch.setattr("aegisx_agent.runner.SystemCollector", FakeCollector)
    monkeypatch.setattr("aegisx_agent.runner.ProcessCollector", process_collector)
    monkeypatch.setattr("aegisx_agent.runner.NetworkCollector", network_collector)

    result = await collect_once(settings, client=FakeClient())

    assert result.accepted == 3
    assert constructor_arguments == {
        "process": {
            "max_processes": 40,
            "state_path": tmp_path / "process-state.json",
            "emit_resource_usage": True,
        },
        "network": {
            "max_connections": 200,
            "state_path": tmp_path / "network-state.json",
            "emit_observations": True,
        },
    }
