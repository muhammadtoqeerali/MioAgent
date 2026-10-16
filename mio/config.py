"""Configuration, with secrets restricted to environment variables."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mio_api_token: str = Field(min_length=32)
    mio_database_url: str = "sqlite+pysqlite:///./data/mioagent.db"
    mio_workspace_root: Path = Path(".")
    mio_poll_seconds: float = Field(default=1.0, ge=0.1, le=60)
    mio_demo_step_seconds: float = Field(default=0.5, ge=0, le=60)

    # Phase 2: local inference on loopback. Cloud disabled unless explicitly enabled.
    mio_local_base_url: str = "http://127.0.0.1:11434/v1"
    mio_local_model: str = ""
    mio_allow_cloud: bool = False
    mio_cloud_base_url: str = "https://api.openai.com/v1"
    mio_cloud_model: str = ""
    mio_cloud_api_key: SecretStr = SecretStr("")
    mio_model_route: Literal["auto", "local", "cloud"] = "auto"

    # v0.3: off by default; project drafts do not execute generated code.
    mio_enable_project_mode: bool = False
    mio_project_root: Path = Path("/var/tmp/mioagent-private-projects")


    # v0.3B: owner-flag-only Bubblewrap unittest verification, disabled initially.
    mio_enable_sandbox_verify: bool = False
