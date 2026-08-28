from fastapi import FastAPI

from aegisx_api.api.router import router
from aegisx_api.config import Settings, get_settings
from aegisx_api.db.session import create_engine, create_session_factory
from aegisx_api.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    app = FastAPI(
        title=resolved_settings.api_title,
        version=resolved_settings.api_version,
    )
    app.state.settings = resolved_settings
    app.state.engine = create_engine(resolved_settings)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.include_router(router)
    return app


app = create_app()
