"""Application configuration: the ONLY module that reads environment variables.

Variables are grouped with a ``__`` delimiter (``DATABASE__URL``, ``AI__PROVIDER``...).
Structure and formats are validated by pydantic when ``Settings`` is built, so a bad
environment stops the process at startup instead of at the first request.

Open/closed note: the set of valid AI providers is NOT listed here. ``load_settings``
receives it from its caller; the composition root (``app.bootstrap``) feeds it the keys
of ``infrastructure/ai/registry.py``. Adding a provider is therefore a new adapter file
plus one registry line, with no edit to this module, and configuration does not import
any adapter.
"""

from collections.abc import Collection
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DATABASE_SCHEME = "postgresql+psycopg://"
REDIS_SCHEMES = ("redis://", "rediss://")


class ConfigurationError(ValueError):
    """The environment is structurally valid but names something that does not exist."""


class _Group(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AppSettings(_Group):
    env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    health_check_timeout_seconds: float = Field(default=2.0, gt=0)


class DatabaseSettings(_Group):
    url: str

    @field_validator("url")
    @classmethod
    def _require_postgresql_psycopg(cls, value: str) -> str:
        if not value.startswith(DATABASE_SCHEME):
            raise ValueError(f"DATABASE__URL must start with {DATABASE_SCHEME!r}")
        return value


class RedisSettings(_Group):
    url: str

    @field_validator("url")
    @classmethod
    def _require_redis_scheme(cls, value: str) -> str:
        if not value.startswith(REDIS_SCHEMES):
            raise ValueError(f"REDIS__URL must start with one of {REDIS_SCHEMES}")
        return value


class AiSettings(_Group):
    provider: str = "fake"
    model: str = "fake-1"


class CorsSettings(_Group):
    allowed_origins: list[str] = ["http://localhost:3000"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__", frozen=True, extra="ignore")

    app: AppSettings = AppSettings()
    database: DatabaseSettings
    redis: RedisSettings
    ai: AiSettings = AiSettings()
    cors: CorsSettings = CorsSettings()


def load_settings(*, valid_ai_providers: Collection[str]) -> Settings:
    """Read and validate the environment, failing fast on anything unusable."""
    settings = Settings()
    if settings.ai.provider not in valid_ai_providers:
        options = ", ".join(sorted(valid_ai_providers))
        raise ConfigurationError(
            f"AI__PROVIDER={settings.ai.provider!r} is not a registered provider. "
            f"Valid options: {options}"
        )
    return settings
