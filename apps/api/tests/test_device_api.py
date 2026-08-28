from pathlib import Path

import httpx
import pytest

from aegisx_api.config import Settings
from aegisx_api.db.base import Base
from aegisx_api.main import create_app


@pytest.fixture
async def client(tmp_path: Path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'api.db'}"
    settings = Settings(_env_file=None, environment="test", database_url=database_url)
    app = create_app(settings)
    async with app.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_readiness_checks_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_register_device_returns_token_once(client: httpx.AsyncClient) -> None:
    payload = {
        "external_id": "fedora-laptop-01",
        "name": "Fedora Laptop",
        "os": "Linux",
        "os_version": "Fedora 42",
        "kernel": "6.15.9",
        "architecture": "x86_64",
    }

    response = await client.post("/api/v1/devices/register", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["device"]["external_id"] == payload["external_id"]
    assert len(body["token"]) >= 43

    duplicate = await client.post("/api/v1/devices/register", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "device_already_registered"


@pytest.mark.asyncio
async def test_register_device_rejects_unsupported_os(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/devices/register",
        json={
            "external_id": "windows-host",
            "name": "Windows Host",
            "os": "Windows",
            "os_version": "11",
            "kernel": "10.0",
            "architecture": "x86_64",
        },
    )

    assert response.status_code == 422
