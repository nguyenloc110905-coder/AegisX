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
    max_network_connections: int = Field(default=200, ge=1, le=1000)
    batch_size: int = Field(default=100, ge=1, le=100)
    max_outbox_events: int = Field(default=10_000, ge=100, le=1_000_000)
    local_telemetry_max_bytes: int = Field(
        default=256 * 1024 * 1024,
        ge=64 * 1024 * 1024,
        le=10 * 1024 * 1024 * 1024,
        validation_alias="AEGISX_LOCAL_TELEMETRY_MAX_BYTES",
    )
    request_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    collection_interval_seconds: float = Field(default=30.0, ge=5, le=3600)
    max_backoff_seconds: float = Field(default=300.0, ge=5, le=3600)
    emit_process_resource_usage: bool = Field(
        default=False,
        validation_alias="AEGISX_EMIT_PROCESS_RESOURCE_USAGE",
    )
    emit_network_snapshot_observations: bool = Field(
        default=False,
        validation_alias="AEGISX_EMIT_NETWORK_SNAPSHOT_OBSERVATIONS",
    )
