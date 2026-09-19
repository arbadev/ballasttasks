"""The ``rate_limit`` settings group, and what the composition root builds from it."""

import pytest
from app.application.ports.rate_limiter import RateLimitPolicy
from app.infrastructure.rate_limit.fail_open_rate_limiter import FailOpenRateLimiter
from pydantic import ValidationError

from app.bootstrap import build_container
from app.bootstrap import load_settings as load_app_settings
from app.infrastructure.config.settings import load_settings

PROVIDERS = {"fake"}


def test_rate_limiting_is_on_by_default_with_a_strict_auth_policy(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    rate_limit = load_settings(valid_ai_providers=PROVIDERS).rate_limit

    assert rate_limit.enabled is True
    assert rate_limit.trust_proxy is False
    assert rate_limit.key_prefix == "ratelimit"
    assert (rate_limit.auth.limit, rate_limit.auth.window_seconds) == (10, 60)
    assert (rate_limit.authenticated.limit, rate_limit.authenticated.window_seconds) == (120, 60)
    assert (rate_limit.anonymous.limit, rate_limit.anonymous.window_seconds) == (60, 60)
    assert rate_limit.auth.limit < rate_limit.anonymous.limit < rate_limit.authenticated.limit


def test_each_rate_limit_variable_overrides_its_default_alone(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("RATE_LIMIT__ENABLED", "false")
    minimal_env.setenv("RATE_LIMIT__TRUST_PROXY", "true")
    minimal_env.setenv("RATE_LIMIT__KEY_PREFIX", "staging-ratelimit")
    minimal_env.setenv("RATE_LIMIT__AUTH__LIMIT", "3")
    minimal_env.setenv("RATE_LIMIT__ANONYMOUS__WINDOW_SECONDS", "10")

    rate_limit = load_settings(valid_ai_providers=PROVIDERS).rate_limit

    assert rate_limit.enabled is False
    assert rate_limit.trust_proxy is True
    assert rate_limit.key_prefix == "staging-ratelimit"
    assert (rate_limit.auth.limit, rate_limit.auth.window_seconds) == (3, 60)
    assert (rate_limit.anonymous.limit, rate_limit.anonymous.window_seconds) == (60, 10)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("RATE_LIMIT__AUTH__LIMIT", "0"),
        ("RATE_LIMIT__AUTHENTICATED__LIMIT", "-1"),
        ("RATE_LIMIT__ANONYMOUS__WINDOW_SECONDS", "0"),
        ("RATE_LIMIT__AUTH__WINDOW_SECONDS", "1.5"),
        ("RATE_LIMIT__KEY_PREFIX", ""),
    ],
)
def test_an_unusable_rate_limit_value_fails_at_startup(
    minimal_env: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    minimal_env.setenv(variable, value)

    with pytest.raises(ValidationError, match="rate_limit"):
        load_settings(valid_ai_providers=PROVIDERS)


def test_a_misspelt_rate_limit_variable_is_rejected(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("RATE_LIMIT__AUTH__LIMITT", "3")

    with pytest.raises(ValidationError, match="rate_limit"):
        load_settings(valid_ai_providers=PROVIDERS)


async def test_the_container_carries_the_policies_and_a_limiter_that_fails_open(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("RATE_LIMIT__AUTH__LIMIT", "3")
    minimal_env.setenv("RATE_LIMIT__TRUST_PROXY", "true")

    container = build_container(load_app_settings())
    rate_limiting = container.rate_limiting
    await container.aclose()

    assert isinstance(rate_limiting.limiter, FailOpenRateLimiter)
    assert rate_limiting.enabled is True
    assert rate_limiting.trust_proxy is True
    assert rate_limiting.auth == RateLimitPolicy(name="auth", limit=3, window_seconds=60)
    assert rate_limiting.authenticated == RateLimitPolicy(
        name="authenticated", limit=120, window_seconds=60
    )
    assert rate_limiting.anonymous == RateLimitPolicy(name="anonymous", limit=60, window_seconds=60)
