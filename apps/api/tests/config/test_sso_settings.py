"""The ``sso`` settings group and the identity provider registry.

Single sign-on ships disabled. Enabling a provider is one name in ``SSO__ENABLED_PROVIDERS``;
each adapter's factory decides what it needs and stops the process at startup, naming the
variable, when it is missing.
"""

import pytest
from pydantic import ValidationError

from app.bootstrap import build_container, load_settings
from app.infrastructure.config import settings as config
from app.infrastructure.config.settings import ConfigurationError
from app.infrastructure.identity.fake import FakeIdentityProvider
from app.infrastructure.identity.google import GoogleIdentityProvider
from app.infrastructure.identity.registry import IDENTITY_PROVIDERS, build_identity_providers

GOOGLE_SECRET = "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3456789"


def test_single_sign_on_is_disabled_by_default(minimal_env: pytest.MonkeyPatch) -> None:
    settings = load_settings()

    assert settings.sso.enabled_providers == []
    assert settings.sso.google_client_id is None
    assert settings.sso.google_client_secret is None
    assert settings.sso.api_public_base_url == "http://localhost:8000"
    assert settings.sso.web_callback_url == "http://localhost:3000/auth/callback"
    assert build_identity_providers(settings) == {}


async def test_the_container_starts_without_any_sso_variable(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    container = build_container(load_settings())

    try:
        assert dict(container.identity_providers) == {}
    finally:
        await container.aclose()


def test_the_registry_holds_google_and_the_fake() -> None:
    assert set(IDENTITY_PROVIDERS) == {"fake", "google"}


def test_the_fake_provider_needs_no_credentials(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("SSO__ENABLED_PROVIDERS", '["fake"]')

    providers = build_identity_providers(load_settings())

    assert list(providers) == ["fake"]
    assert isinstance(providers["fake"], FakeIdentityProvider)


def test_the_fake_provider_refuses_to_start_in_production(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    """It signs anybody in as its demo user: a demo convenience, never a production door."""
    minimal_env.setenv("APP__ENV", "production")
    minimal_env.setenv("SSO__ENABLED_PROVIDERS", '["fake"]')

    with pytest.raises(ConfigurationError, match="APP__ENV"):
        build_container(load_settings())


def test_google_is_built_from_its_credentials(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("SSO__ENABLED_PROVIDERS", '["google"]')
    minimal_env.setenv("SSO__GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    minimal_env.setenv("SSO__GOOGLE_CLIENT_SECRET", GOOGLE_SECRET)

    providers = build_identity_providers(load_settings())

    assert isinstance(providers["google"], GoogleIdentityProvider)


@pytest.mark.parametrize(
    ("present", "missing"),
    [
        ({}, "SSO__GOOGLE_CLIENT_ID"),
        ({"SSO__GOOGLE_CLIENT_SECRET": GOOGLE_SECRET}, "SSO__GOOGLE_CLIENT_ID"),
        ({"SSO__GOOGLE_CLIENT_ID": "client-id"}, "SSO__GOOGLE_CLIENT_SECRET"),
        ({"SSO__GOOGLE_CLIENT_ID": "client-id", "SSO__GOOGLE_CLIENT_SECRET": ""}, "_SECRET"),
        ({"SSO__GOOGLE_CLIENT_ID": " ", "SSO__GOOGLE_CLIENT_SECRET": GOOGLE_SECRET}, "_ID"),
    ],
)
def test_google_without_its_credentials_fails_at_startup_naming_the_variable(
    minimal_env: pytest.MonkeyPatch, present: dict[str, str], missing: str
) -> None:
    minimal_env.setenv("SSO__ENABLED_PROVIDERS", '["google"]')
    for name, value in present.items():
        minimal_env.setenv(name, value)

    with pytest.raises(ConfigurationError) as error:
        build_container(load_settings())

    assert missing in str(error.value)
    assert GOOGLE_SECRET not in str(error.value)


def test_google_credentials_are_not_needed_while_google_is_disabled(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("SSO__ENABLED_PROVIDERS", '["fake"]')

    assert list(build_identity_providers(load_settings())) == ["fake"]


def test_an_unknown_provider_fails_at_startup_and_lists_the_registered_ones(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("SSO__ENABLED_PROVIDERS", '["google", "myspace"]')

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    message = str(error.value)
    assert "SSO__ENABLED_PROVIDERS" in message
    assert "myspace" in message
    for name in IDENTITY_PROVIDERS:
        assert name in message


def test_a_provider_listed_twice_is_rejected(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("SSO__ENABLED_PROVIDERS", '["fake", "fake"]')

    with pytest.raises(ValidationError, match="ENABLED_PROVIDERS"):
        load_settings()


async def test_a_new_provider_needs_only_a_registry_entry(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    class OtherProvider(FakeIdentityProvider):
        name = "other"

    minimal_env.setitem(IDENTITY_PROVIDERS, "other", lambda settings: OtherProvider())
    minimal_env.setenv("SSO__ENABLED_PROVIDERS", '["other"]')

    container = build_container(load_settings())

    try:
        assert isinstance(container.identity_providers["other"], OtherProvider)
    finally:
        await container.aclose()


def test_the_google_secret_never_appears_in_a_repr_or_a_dump(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("SSO__GOOGLE_CLIENT_SECRET", GOOGLE_SECRET)

    settings = load_settings()

    assert GOOGLE_SECRET not in repr(settings)
    assert GOOGLE_SECRET not in str(settings.model_dump())
    assert GOOGLE_SECRET not in settings.model_dump_json()


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("SSO__API_PUBLIC_BASE_URL", "localhost:8000"),
        ("SSO__API_PUBLIC_BASE_URL", "ftp://api.example"),
        ("SSO__API_PUBLIC_BASE_URL", "https://api.example/?next=x"),
        ("SSO__API_PUBLIC_BASE_URL", "https://api.example/#frag"),
        ("SSO__API_PUBLIC_BASE_URL", "https://user:pw@api.example"),
        ("SSO__WEB_CALLBACK_URL", "/auth/callback"),
        ("SSO__WEB_CALLBACK_URL", "javascript:alert(1)"),
        ("SSO__WEB_CALLBACK_URL", "https://app.example/auth/callback?code=x"),
        ("SSO__WEB_CALLBACK_URL", "https://app.example/auth/callback#x"),
    ],
)
def test_redirect_targets_must_be_plain_absolute_http_urls(
    minimal_env: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    minimal_env.setenv(variable, value)

    with pytest.raises(ValidationError, match=variable):
        load_settings()


def test_a_trailing_slash_on_the_api_base_url_is_dropped(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("SSO__API_PUBLIC_BASE_URL", "https://api.example/")

    assert load_settings().sso.api_public_base_url == "https://api.example"


def test_load_settings_without_a_provider_list_accepts_only_disabled_sso(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    """Callers that know no registry (older tests, scripts) still load a default environment."""
    assert config.load_settings(valid_ai_providers=("fake",)).sso.enabled_providers == []


def test_the_registry_itself_refuses_a_name_it_does_not_hold(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    """Defence in depth: settings built without ``load_settings`` skip its check."""
    minimal_env.setenv("SSO__ENABLED_PROVIDERS", '["myspace"]')

    with pytest.raises(ConfigurationError, match="SSO__ENABLED_PROVIDERS"):
        build_identity_providers(config.Settings())
