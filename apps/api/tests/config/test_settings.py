import pytest
from pydantic import ValidationError

from app.infrastructure.config.settings import ConfigurationError, Settings, load_settings
from tests.conftest import DOWN_DATABASE_URL, DOWN_REDIS_URL, TEST_JWT_SECRET

PROVIDERS = ("fake",)


def test_missing_required_variables_fail_fast(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError) as error:
        load_settings(valid_ai_providers=PROVIDERS)

    missing = {".".join(str(part) for part in e["loc"]) for e in error.value.errors()}
    assert missing == {"database", "redis", "auth"}


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
    assert settings.auth.jwt_secret.get_secret_value() == TEST_JWT_SECRET
    assert settings.auth.jwt_algorithm == "HS256"
    assert settings.auth.access_token_expire_minutes == 30


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


def test_missing_jwt_secret_fails_fast_and_names_the_group(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.delenv("AUTH__JWT_SECRET")

    with pytest.raises(ValidationError, match="auth"):
        load_settings(valid_ai_providers=PROVIDERS)


@pytest.mark.parametrize("secret", ["", "short", "x" * 31])
def test_a_jwt_secret_shorter_than_32_bytes_is_rejected(
    minimal_env: pytest.MonkeyPatch, secret: str
) -> None:
    minimal_env.setenv("AUTH__JWT_SECRET", secret)

    with pytest.raises(ValidationError, match="AUTH__JWT_SECRET"):
        load_settings(valid_ai_providers=PROVIDERS)


@pytest.mark.parametrize(
    ("algorithm", "length", "accepted"),
    [
        ("HS256", 32, True),
        ("HS384", 47, False),
        ("HS384", 48, True),
        ("HS512", 63, False),
        ("HS512", 64, True),
    ],
)
def test_the_jwt_secret_must_be_as_long_as_the_algorithm_digest(
    minimal_env: pytest.MonkeyPatch, algorithm: str, length: int, accepted: bool
) -> None:
    """RFC 7518 section 3.2: an HMAC key shorter than the hash output weakens the signature."""
    minimal_env.setenv("AUTH__JWT_ALGORITHM", algorithm)
    minimal_env.setenv("AUTH__JWT_SECRET", "k" * length)

    if accepted:
        assert load_settings(valid_ai_providers=PROVIDERS).auth.jwt_algorithm == algorithm
    else:
        with pytest.raises(ValidationError, match="AUTH__JWT_SECRET"):
            load_settings(valid_ai_providers=PROVIDERS)


@pytest.mark.parametrize("algorithm", ["none", "RS256", "hs256", ""])
def test_only_hmac_jwt_algorithms_are_accepted(
    minimal_env: pytest.MonkeyPatch, algorithm: str
) -> None:
    minimal_env.setenv("AUTH__JWT_ALGORITHM", algorithm)

    with pytest.raises(ValidationError):
        load_settings(valid_ai_providers=PROVIDERS)


@pytest.mark.parametrize("minutes", ["0", "-5", "soon"])
def test_access_token_lifetime_must_be_a_positive_number_of_minutes(
    minimal_env: pytest.MonkeyPatch, minutes: str
) -> None:
    minimal_env.setenv("AUTH__ACCESS_TOKEN_EXPIRE_MINUTES", minutes)

    with pytest.raises(ValidationError):
        load_settings(valid_ai_providers=PROVIDERS)


def test_auth_variables_override_defaults(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("AUTH__ACCESS_TOKEN_EXPIRE_MINUTES", "5")

    assert load_settings(valid_ai_providers=PROVIDERS).auth.access_token_expire_minutes == 5


def test_the_jwt_secret_never_appears_in_a_repr_or_a_dump(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    settings = load_settings(valid_ai_providers=PROVIDERS)

    assert TEST_JWT_SECRET not in repr(settings)
    assert TEST_JWT_SECRET not in str(settings.model_dump())
    assert TEST_JWT_SECRET not in settings.model_dump_json()
