"""Application configuration: the ONLY module that reads environment variables.

Variables are grouped with a ``__`` delimiter (``DATABASE__URL``, ``AI__PROVIDER``...).
Structure and formats are validated by pydantic when ``Settings`` is built, so a bad
environment stops the process at startup instead of at the first request.

Open/closed note: the set of valid AI providers is NOT listed here. ``load_settings``
receives it from its caller; the composition root (``app.bootstrap``) feeds it the keys
of ``infrastructure/ai/registry.py``. Adding a provider is therefore a new adapter file
plus one registry line, with no edit to this module, and configuration does not import
any adapter. The same goes for single sign-on: ``SSO__ENABLED_PROVIDERS`` is checked
against the keys of ``infrastructure/identity/registry.py``.
"""

from collections.abc import Collection
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

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


class StorageSettings(_Group):
    provider: str = "local"
    local_directory: Path = Path("var/attachments")
    max_bytes: int = Field(default=10 * 1024 * 1024, gt=0)


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


def _plain_http_url(value: str, variable: str) -> str:
    """An absolute http(s) URL with nothing a redirect target should carry: no credentials,
    no query, no fragment. The message names the variable and never the value."""
    parts = urlsplit(value)
    plain = (
        parts.scheme in {"http", "https"}
        and bool(parts.hostname)
        and parts.username is None
        and parts.password is None
        and not parts.query
        and not parts.fragment
        and "?" not in value
        and "#" not in value
    )
    if not plain:
        raise ValueError(
            f"{variable} must be an absolute http(s) URL without credentials, query or fragment"
        )
    return value


class SsoSettings(_Group):
    """Single sign-on. Disabled unless a provider is named in ``enabled_providers``.

    Which names exist, and what each needs, is not known here: the identity provider
    registry decides (``infrastructure/identity/registry.py``), so a new provider adds
    fields to this group at most, never a rule.
    """

    enabled_providers: list[str] = []
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    # The only redirect targets single sign-on uses; no request can name another.
    api_public_base_url: str = "http://localhost:8000"
    web_callback_url: str = "http://localhost:3000/auth/callback"

    @field_validator("enabled_providers")
    @classmethod
    def _no_provider_twice(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("SSO__ENABLED_PROVIDERS lists a provider more than once")
        return value

    @field_validator("api_public_base_url")
    @classmethod
    def _require_a_plain_api_base_url(cls, value: str) -> str:
        return _plain_http_url(value, "SSO__API_PUBLIC_BASE_URL").rstrip("/")

    @field_validator("web_callback_url")
    @classmethod
    def _require_a_plain_web_callback_url(cls, value: str) -> str:
        return _plain_http_url(value, "SSO__WEB_CALLBACK_URL")


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
    sso: SsoSettings = SsoSettings()
    rate_limit: RateLimitSettings = RateLimitSettings()
    storage: StorageSettings = StorageSettings()


def load_settings(
    *, valid_ai_providers: Collection[str], valid_sso_providers: Collection[str] = ()
) -> Settings:
    """Read and validate the environment, failing fast on anything unusable."""
    settings = Settings()
    unknown = [name for name in settings.sso.enabled_providers if name not in valid_sso_providers]
    if unknown:
        options = ", ".join(sorted(valid_sso_providers)) or "(none)"
        raise ConfigurationError(
            f"SSO__ENABLED_PROVIDERS names {', '.join(map(repr, unknown))}, which is not a "
            f"registered provider. Valid options: {options}"
        )
    if settings.ai.provider not in valid_ai_providers:
        options = ", ".join(sorted(valid_ai_providers))
        raise ConfigurationError(
            f"AI__PROVIDER={settings.ai.provider!r} is not a registered provider. "
            f"Valid options: {options}"
        )
    return settings
