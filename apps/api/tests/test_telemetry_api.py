from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from aegisx_api.config import Settings
from aegisx_api.db.base import Base
from aegisx_api.main import create_app
from aegisx_api.models.detection import Detection
from aegisx_api.models.event import Event


@pytest.fixture
async def app_and_client(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'telemetry.db'}",
    )
    app = create_app(settings)
    async with app.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield app, client
    await app.state.engine.dispose()


async def register(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/api/v1/devices/register",
        json={
            "external_id": "telemetry-device-01",
            "name": "Telemetry Device",
            "os": "Linux",
            "os_version": "Fedora 42",
            "kernel": "6.15.9",
            "architecture": "x86_64",
        },
    )
    return response.json()["token"]


def process_started_event(event_id: str) -> dict:
    return {
        "id": event_id,
        "schema_version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": "process.started",
        "source": "process_collector",
        "severity_hint": "normal",
        "data": {
            "pid": 4242,
            "ppid": 1,
            "name": "python",
            "executable": "/usr/bin/python3",
            "user": "student",
            "command_line": ["python3", "demo.py"],
            "started_at": datetime.now(UTC).isoformat(),
        },
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_ingestion_requires_valid_device_token(app_and_client) -> None:
    _, client = app_and_client
    response = await client.post(
        "/api/v1/telemetry/events",
        headers={"Authorization": "Bearer invalid-token"},
        json={"events": [process_started_event(str(uuid4()))]},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_device_token"


@pytest.mark.asyncio
async def test_ingestion_is_typed_and_idempotent(app_and_client) -> None:
    app, client = app_and_client
    token = await register(client)
    event_id = str(uuid4())
    request = {"events": [process_started_event(event_id)]}
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post("/api/v1/telemetry/events", headers=headers, json=request)
    second = await client.post("/api/v1/telemetry/events", headers=headers, json=request)

    assert first.status_code == 202
    assert first.json() == {"accepted": 1, "duplicates": 0}
    assert second.status_code == 202
    assert second.json() == {"accepted": 0, "duplicates": 1}
    async with app.state.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Event))
        detection_count = await session.scalar(select(func.count()).select_from(Detection))
    assert count == 1
    assert detection_count == 1


@pytest.mark.asyncio
async def test_irrelevant_event_persists_without_detection(app_and_client) -> None:
    app, client = app_and_client
    token = await register(client)
    response = await client.post(
        "/api/v1/telemetry/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "id": str(uuid4()),
                    "schema_version": 1,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event_type": "system.status",
                    "source": "system_collector",
                    "severity_hint": "normal",
                    "data": {
                        "hostname": "test",
                        "os": "Linux",
                        "kernel": "test",
                        "uptime_seconds": 1,
                        "cpu_count": 1,
                        "memory_total_bytes": 1024,
                    },
                    "metadata": {},
                }
            ]
        },
    )

    assert response.status_code == 202
    async with app.state.session_factory() as session:
        detection_count = await session.scalar(select(func.count()).select_from(Detection))
    assert detection_count == 0


@pytest.mark.asyncio
async def test_ingestion_rejects_payload_for_wrong_event_type(app_and_client) -> None:
    _, client = app_and_client
    token = await register(client)
    event = process_started_event(str(uuid4()))
    event["event_type"] = "system.status"

    response = await client.post(
        "/api/v1/telemetry/events",
        headers={"Authorization": f"Bearer {token}"},
        json={"events": [event]},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingestion_accepts_typed_network_listener(app_and_client) -> None:
    app, client = app_and_client
    token = await register(client)
    event_id = str(uuid4())
    event = {
        "id": event_id,
        "schema_version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": "network.listener_observed",
        "source": "network_collector",
        "severity_hint": "normal",
        "data": {
            "pid": 4242,
            "local_ip": "127.0.0.1",
            "local_port": 8080,
            "protocol": "tcp",
            "state": "LISTEN",
        },
        "metadata": {},
    }

    response = await client.post(
        "/api/v1/telemetry/events",
        headers={"Authorization": f"Bearer {token}"},
        json={"events": [event]},
    )

    assert response.status_code == 202
    async with app.state.session_factory() as session:
        stored = await session.scalar(select(Event).where(Event.id == UUID(event_id)))
    assert stored is not None
    assert stored.local_port == 8080


@pytest.mark.asyncio
async def test_ingestion_enforces_configured_batch_limit(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'batch-limit.db'}",
        telemetry_batch_limit=1,
    )
    app = create_app(settings)
    async with app.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await register(client)
        response = await client.post(
            "/api/v1/telemetry/events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "events": [
                    process_started_event(str(uuid4())),
                    process_started_event(str(uuid4())),
                ]
            },
        )
    await app.state.engine.dispose()

    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "telemetry_batch_too_large", "limit": 1}
