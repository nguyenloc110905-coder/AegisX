import httpx
import pytest

from aegisx_api.config import Settings
from aegisx_api.main import create_app


@pytest.mark.asyncio
async def test_liveness_does_not_require_database() -> None:
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///missing.db")
    transport = httpx.ASGITransport(app=create_app(settings))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
