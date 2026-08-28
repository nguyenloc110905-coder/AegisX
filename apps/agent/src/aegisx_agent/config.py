from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    api_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias=AliasChoices("AEGISX_API_URL", "API_URL"),
    )
    state_directory: Path = Field(
        default=Path.home() / ".local" / "state" / "aegisx",
        validation_alias="AEGISX_AGENT_STATE_DIR",
    )
    max_processes: int = Field(default=40, ge=1, le=49)
    batch_size: int = Field(default=100, ge=1, le=100)
    max_outbox_events: int = Field(default=10_000, ge=100, le=1_000_000)
    request_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
