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


def _startup_error() -> ValidationError:
    with pytest.raises(ValidationError) as error:
        load_settings(valid_ai_providers=PROVIDERS)
    return error.value


def _assert_never_shown(value: str, error: ValidationError) -> None:
    """Not even a fragment: pydantic shortens long inputs, which still shows part of a key."""
    fragments = {value[start : start + 8] for start in range(len(value) - 7)}
    for text in (str(error), repr(error)):
        assert not [fragment for fragment in fragments if fragment in text]


@pytest.mark.parametrize(
    ("algorithm", "secret"),
    [
        ("HS256", "S3cretValue-31-bytes-long-abcde"),
        ("HS384", "S3cretValue-47-bytes-long-" + "a" * 21),
        ("HS512", "S3cretValue-63-bytes-long-" + "a" * 37),
    ],
)
def test_a_rejected_jwt_secret_never_appears_in_the_startup_error(
    minimal_env: pytest.MonkeyPatch, algorithm: str, secret: str
) -> None:
    """A key that is one byte too short is still a real key: it must not reach the logs."""
    minimal_env.setenv("AUTH__JWT_ALGORITHM", algorithm)
    minimal_env.setenv("AUTH__JWT_SECRET", secret)

    error = _startup_error()

    assert "AUTH__JWT_SECRET" in str(error)
    _assert_never_shown(secret, error)


def test_a_misspelt_auth_variable_does_not_echo_its_value(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    secret = "S3cretValue-under-a-misspelt-name-" + "a" * 30
    minimal_env.setenv("AUTH__JWT_SECRT", secret)

    error = _startup_error()

    assert "jwt_secrt" in str(error)
    _assert_never_shown(secret, error)


def test_a_rejected_database_url_never_shows_its_password(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("DATABASE__URL", "postgresql://app:Db-Passw0rd-xyz@db/app")

    error = _startup_error()

    assert "DATABASE__URL" in str(error)
    _assert_never_shown("Db-Passw0rd-xyz", error)


def test_a_rejected_redis_url_never_shows_its_password(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("REDIS__URL", "http://:Redis-Passw0rd-xyz@redis:6379/0")

    error = _startup_error()

    assert "REDIS__URL" in str(error)
    _assert_never_shown("Redis-Passw0rd-xyz", error)


TEST_AI_KEY = "sk-test-0123456789abcdef-never-a-real-key"


def test_ai_defaults_need_no_key(minimal_env: pytest.MonkeyPatch) -> None:
    ai = load_settings(valid_ai_providers=PROVIDERS).ai

    assert ai.api_key is None
    assert ai.base_url is None
    assert ai.timeout_seconds == 30.0
    assert ai.check_cache_seconds == 30.0


def test_ai_variables_override_defaults(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("AI__PROVIDER", "other")
    minimal_env.setenv("AI__API_KEY", TEST_AI_KEY)
    minimal_env.setenv("AI__BASE_URL", "https://proxy.example/v1")
    minimal_env.setenv("AI__TIMEOUT_SECONDS", "12.5")
    minimal_env.setenv("AI__CHECK_CACHE_SECONDS", "5")

    ai = load_settings(valid_ai_providers=("fake", "other")).ai

    assert ai.api_key is not None
    assert ai.api_key.get_secret_value() == TEST_AI_KEY
    assert ai.base_url == "https://proxy.example/v1"
    assert ai.timeout_seconds == 12.5
    assert ai.check_cache_seconds == 5.0


@pytest.mark.parametrize("key", [None, "", "   "])
def test_settings_demand_no_api_key_of_any_provider(
    minimal_env: pytest.MonkeyPatch, key: str | None
) -> None:
    """Whether a provider needs a key is its registry factory's rule (``test_bootstrap``):
    a keyless provider must be addable with no edit to the settings module."""
    minimal_env.setenv("AI__PROVIDER", "other")
    if key is not None:
        minimal_env.setenv("AI__API_KEY", key)

    ai = load_settings(valid_ai_providers=("fake", "other")).ai

    assert ai.provider == "other"
    assert ai.api_key is None


def test_an_unknown_provider_is_reported_before_its_missing_key(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    """A typo in AI__PROVIDER must not be answered with "set AI__API_KEY"."""
    minimal_env.setenv("AI__PROVIDER", "skynet")

    with pytest.raises(ConfigurationError, match="AI__PROVIDER"):
        load_settings(valid_ai_providers=PROVIDERS)


def test_blank_optional_ai_variables_mean_unset(minimal_env: pytest.MonkeyPatch) -> None:
    """``.env.example`` ships them empty; that must not stop the default stack."""
    minimal_env.setenv("AI__API_KEY", "")
    minimal_env.setenv("AI__BASE_URL", "")

    ai = load_settings(valid_ai_providers=PROVIDERS).ai

    assert ai.api_key is None
    assert ai.base_url is None


@pytest.mark.parametrize("timeout", ["0", "-1"])
def test_the_ai_timeout_must_be_positive(minimal_env: pytest.MonkeyPatch, timeout: str) -> None:
    minimal_env.setenv("AI__TIMEOUT_SECONDS", timeout)

    with pytest.raises(ValidationError, match="timeout_seconds"):
        load_settings(valid_ai_providers=PROVIDERS)


def test_the_ai_check_cache_may_be_turned_off_but_not_negative(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("AI__CHECK_CACHE_SECONDS", "0")
    assert load_settings(valid_ai_providers=PROVIDERS).ai.check_cache_seconds == 0

    minimal_env.setenv("AI__CHECK_CACHE_SECONDS", "-1")
    with pytest.raises(ValidationError, match="check_cache_seconds"):
        load_settings(valid_ai_providers=PROVIDERS)


def test_the_ai_base_url_must_be_http(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("AI__BASE_URL", "ftp://proxy.example")

    with pytest.raises(ValidationError, match="AI__BASE_URL"):
        load_settings(valid_ai_providers=PROVIDERS)


def test_the_ai_api_key_never_appears_in_a_repr_or_a_dump(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("AI__PROVIDER", "other")
    minimal_env.setenv("AI__API_KEY", TEST_AI_KEY)

    settings = load_settings(valid_ai_providers=("fake", "other"))

    assert TEST_AI_KEY not in repr(settings)
    assert TEST_AI_KEY not in str(settings.model_dump())
    assert TEST_AI_KEY not in settings.model_dump_json()


def test_the_ai_api_key_never_appears_in_a_startup_error(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("AI__API_KEY", TEST_AI_KEY)
    minimal_env.setenv("AI__TIMEOUT_SECONDS", "-1")

    _assert_never_shown(TEST_AI_KEY, _startup_error())


def test_the_ai_api_key_never_appears_when_the_provider_is_unknown(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("AI__PROVIDER", "skynet")
    minimal_env.setenv("AI__API_KEY", TEST_AI_KEY)

    with pytest.raises(ConfigurationError) as error:
        load_settings(valid_ai_providers=PROVIDERS)

    assert TEST_AI_KEY not in str(error.value)
    assert TEST_AI_KEY not in repr(error.value)
