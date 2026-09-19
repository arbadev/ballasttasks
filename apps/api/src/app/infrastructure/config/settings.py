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
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DATABASE_SCHEME = "postgresql+psycopg://"
REDIS_SCHEMES = ("redis://", "rediss://")
HTTP_SCHEMES = ("https://", "http://")
# RFC 7518 section 3.2: an HMAC key must be at least as long as the hash output.
JWT_MIN_SECRET_BYTES = {"HS256": 32, "HS384": 48, "HS512": 64}


class ConfigurationError(ValueError):
    """The environment is structurally valid but names something that does not exist."""


class _Group(BaseModel):
    # A rejected value may be a secret (a signing key, a URL with a password): never echo it.
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


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
    # Whether a provider needs it is that provider's rule: its registry factory enforces it.
    api_key: SecretStr | None = None
    # None means the adapter's own default; set it to go through a proxy or a gateway.
    base_url: str | None = None
    # Total time one generation may take, connection retry and response body included.
    timeout_seconds: float = Field(default=30.0, gt=0)
    # How long a ``check()`` result is reused: the public readiness endpoint must not turn
    # every hit into a keyed provider call. 0 turns the cache off.
    check_cache_seconds: float = Field(default=30.0, ge=0)

    @field_validator("api_key", "base_url", mode="before")
    @classmethod
    def _blank_means_unset(cls, value: object) -> object:
        """``AI__API_KEY=`` left empty in ``.env`` is the same as leaving it out."""
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("base_url")
    @classmethod
    def _require_http(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(HTTP_SCHEMES):
            raise ValueError(f"AI__BASE_URL must start with one of {HTTP_SCHEMES}")
        return value


class CorsSettings(_Group):
    allowed_origins: list[str] = ["http://localhost:3000"]


class AuthSettings(_Group):
    jwt_secret: SecretStr
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, gt=0)

    @model_validator(mode="after")
    def _require_a_long_enough_secret(self) -> Self:
        required = JWT_MIN_SECRET_BYTES[self.jwt_algorithm]
        if len(self.jwt_secret.get_secret_value().encode()) < required:
            raise ValueError(
                f"AUTH__JWT_SECRET must be at least {required} bytes for {self.jwt_algorithm}"
            )
        return self


class _RateLimitPolicySettings(_Group):
    limit: int = Field(gt=0)
    window_seconds: int = Field(default=60, gt=0)


class AuthRateLimitSettings(_RateLimitPolicySettings):
    limit: int = Field(default=10, gt=0)


class AuthenticatedRateLimitSettings(_RateLimitPolicySettings):
    limit: int = Field(default=120, gt=0)


class AnonymousRateLimitSettings(_RateLimitPolicySettings):
    limit: int = Field(default=60, gt=0)


class RateLimitSettings(_Group):
    """Three policies; each variable overrides its own default (``RATE_LIMIT__AUTH__LIMIT``)."""

    enabled: bool = True
    # Only behind a reverse proxy that sets X-Forwarded-For itself: see api/rate_limit.py.
    trust_proxy: bool = False
    # Environments that share one Redis keep their counters apart with this.
    key_prefix: str = Field(default="ratelimit", min_length=1)
    auth: AuthRateLimitSettings = AuthRateLimitSettings()
    authenticated: AuthenticatedRateLimitSettings = AuthenticatedRateLimitSettings()
    anonymous: AnonymousRateLimitSettings = AnonymousRateLimitSettings()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__", frozen=True, extra="ignore", hide_input_in_errors=True
    )

    app: AppSettings = AppSettings()
    database: DatabaseSettings
    redis: RedisSettings
    ai: AiSettings = AiSettings()
    auth: AuthSettings
    cors: CorsSettings = CorsSettings()
    rate_limit: RateLimitSettings = RateLimitSettings()


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
