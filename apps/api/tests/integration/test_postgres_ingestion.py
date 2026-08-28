import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from aegisx_api.config import Settings
from aegisx_api.main import create_app
from aegisx_api.models.device import Device
from aegisx_api.models.event import Event


@pytest.mark.integration
@pytest.mark.asyncio
async def test_device_registration_and_event_ingestion_on_postgresql() -> None:
    database_url = os.getenv("AEGISX_TEST_POSTGRES_URL")
    if database_url is None:
        pytest.skip("AEGISX_TEST_POSTGRES_URL is not configured")
    assert database_url.startswith("postgresql+asyncpg://")

    external_id = f"postgres-integration-{uuid4()}"
    event_id = uuid4()
    app = create_app(Settings(_env_file=None, environment="test", database_url=database_url))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            registration = await client.post(
                "/api/v1/devices/register",
                json={
                    "external_id": external_id,
                    "name": "PostgreSQL integration device",
                    "os": "Linux",
                    "os_version": "test",
                    "kernel": "test",
                    "architecture": "x86_64",
                },
            )
            assert registration.status_code == 201
            token = registration.json()["token"]

            ingestion = await client.post(
                "/api/v1/telemetry/events",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "events": [
                        {
                            "id": str(event_id),
                            "schema_version": 1,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "event_type": "network.listener_observed",
                            "source": "integration_test",
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
                    ]
                },
            )
            assert ingestion.status_code == 202
            assert ingestion.json() == {"accepted": 1, "duplicates": 0}

        async with app.state.session_factory() as session:
            event = await session.scalar(select(Event).where(Event.id == event_id))
            assert event is not None
            assert event.local_port == 8080
            assert event.event_type == "network.listener_observed"

            device = await session.scalar(select(Device).where(Device.external_id == external_id))
            assert device is not None
            await session.delete(device)
            await session.commit()
