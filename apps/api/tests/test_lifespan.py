from unittest.mock import AsyncMock

import pytest

from aegisx_api.config import Settings
from aegisx_api.main import create_app


@pytest.mark.asyncio
async def test_lifespan_disposes_database_engine() -> None:
    app = create_app(Settings(_env_file=None, environment="test"))
    engine = AsyncMock()
    app.state.engine = engine

    async with app.router.lifespan_context(app):
        pass

    engine.dispose.assert_awaited_once_with()
