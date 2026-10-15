"""Centralized configuration. Credentials belong in environment variables, not source code."""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mio_api_token: str = Field(min_length=32)
    mio_database_url: str = "sqlite+pysqlite:///./data/mioagent.db"
    mio_workspace_root: Path = Path(".")
    mio_poll_seconds: float = Field(default=1.0, ge=0.1, le=60)
    mio_demo_step_seconds: float = Field(default=0.5, ge=0, le=60)
