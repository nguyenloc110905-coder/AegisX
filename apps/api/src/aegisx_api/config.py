from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated API configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("AEGISX_ENV", "AEGISX_ENVIRONMENT"),
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        validation_alias=AliasChoices("LOG_LEVEL", "AEGISX_LOG_LEVEL"),
    )
    database_url: str = Field(
        default="postgresql+asyncpg://aegisx:aegisx_dev_only@localhost:5432/aegisx",
        validation_alias=AliasChoices("DATABASE_URL", "AEGISX_DATABASE_URL"),
    )
    api_title: str = "AegisX API"
    api_version: str = "0.1.0"
    telemetry_batch_limit: int = Field(default=100, ge=1, le=1000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
