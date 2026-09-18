import pytest
from pydantic import ValidationError

from app.infrastructure.config.settings import ConfigurationError, Settings, load_settings
from tests.conftest import DOWN_DATABASE_URL, DOWN_REDIS_URL

PROVIDERS = ("fake",)


def test_missing_required_variables_fail_fast(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError) as error:
        load_settings(valid_ai_providers=PROVIDERS)

    missing = {".".join(str(part) for part in e["loc"]) for e in error.value.errors()}
    assert missing == {"database", "redis"}


def test_missing_redis_url_names_the_variable(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE__URL", DOWN_DATABASE_URL)

    with pytest.raises(ValidationError, match="redis"):
        load_settings(valid_ai_providers=PROVIDERS)


def test_defaults_are_applied(minimal_env: pytest.MonkeyPatch) -> None:
    settings = load_settings(valid_ai_providers=PROVIDERS)

    assert settings.app.env == "development"
    assert settings.app.debug is False
    assert settings.database.url == DOWN_DATABASE_URL
    assert settings.redis.url == DOWN_REDIS_URL
    assert settings.ai.provider == "fake"
    assert settings.ai.model == "fake-1"
    assert settings.cors.allowed_origins == ["http://localhost:3000"]


def test_nested_variables_override_defaults(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("APP__ENV", "production")
    minimal_env.setenv("APP__DEBUG", "true")
    minimal_env.setenv("AI__MODEL", "fake-2")
    minimal_env.setenv("CORS__ALLOWED_ORIGINS", '["https://a.example","https://b.example"]')

    settings = load_settings(valid_ai_providers=PROVIDERS)

    assert settings.app.env == "production"
    assert settings.app.debug is True
    assert settings.ai.model == "fake-2"
    assert settings.cors.allowed_origins == ["https://a.example", "https://b.example"]


def test_unknown_ai_provider_fails_and_lists_valid_options(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("AI__PROVIDER", "skynet")

    with pytest.raises(ConfigurationError) as error:
        load_settings(valid_ai_providers=("fake", "other"))

    message = str(error.value)
    assert "AI__PROVIDER" in message
    assert "skynet" in message
    assert "fake" in message
    assert "other" in message


def test_database_url_must_use_the_psycopg_postgresql_driver(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("DATABASE__URL", "sqlite:///./app.db")

    with pytest.raises(ValidationError, match=r"postgresql\+psycopg"):
        load_settings(valid_ai_providers=PROVIDERS)


def test_redis_url_must_be_a_redis_url(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("REDIS__URL", "http://localhost:6379")

    with pytest.raises(ValidationError, match="redis"):
        load_settings(valid_ai_providers=PROVIDERS)


def test_unknown_app_env_is_rejected(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("APP__ENV", "staging-ish")

    with pytest.raises(ValidationError):
        load_settings(valid_ai_providers=PROVIDERS)


def test_settings_are_immutable(minimal_env: pytest.MonkeyPatch) -> None:
    settings = Settings()

    with pytest.raises(ValidationError):
        settings.ai = settings.ai.model_copy(update={"provider": "x"})  # type: ignore[misc]
