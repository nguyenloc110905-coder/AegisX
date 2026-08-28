from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aegisx_api.api.router import router
from aegisx_api.config import Settings, get_settings
from aegisx_api.db.session import create_engine, create_session_factory
from aegisx_api.detection.defaults import create_default_engine
from aegisx_api.logging import configure_logging
from aegisx_api.services.telemetry_ingestion import TelemetryIngestionService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    app = FastAPI(
        title=resolved_settings.api_title,
        version=resolved_settings.api_version,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.engine = create_engine(resolved_settings)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.detection_engine = create_default_engine()
    app.state.telemetry_ingestion_service = TelemetryIngestionService(app.state.detection_engine)
    app.include_router(router)
    return app


app = create_app()
