"""Environment-driven settings for the agent core."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    core_port: int = 8000
    log_level: str = "info"

    postgres_user: str = "cockpit"
    postgres_password: str = "cockpit-dev-pw"  # noqa: S105 — local dev default; override via env
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "cockpit"

    redis_host: str = "redis"
    redis_port: int = 6379

    openai_api_key: str = ""
    openai_realtime_model: str = "gpt-realtime-2"
    openai_translate_model: str = "gpt-realtime-translate"
    openai_voice: str = "alloy"

    default_vertical: str = "hvac"
    verticals_dir: str = "/verticals"

    trace_batch_size: int = 50
    trace_batch_interval_ms: int = 500

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
