import httpx
import pytest

from app.bootstrap import Container, build_container, load_settings
from app.infrastructure.ai.fake import FakeLanguageModel
from app.infrastructure.ai.gemini import GeminiLanguageModel
from app.infrastructure.ai.openrouter import OpenRouterLanguageModel
from app.infrastructure.ai.registry import AI_PROVIDERS, UnknownProviderError, build_language_model
from app.infrastructure.config.settings import AiSettings, ConfigurationError
from app.infrastructure.jobs.queue import CeleryJobQueue
from tests.ai_stubs import TEST_API_KEY


async def test_fake_provider_builds_the_fake_language_model(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("AI__PROVIDER", "fake")

    container = build_container(load_settings())

    try:
        assert isinstance(container.language_model, FakeLanguageModel)
        assert container.language_model.model == "fake-1"
    finally:
        await container.aclose()


async def test_container_registers_the_three_health_checks_in_order(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    container = build_container(load_settings())

    try:
        assert isinstance(container, Container)
        assert [check.name for check in container.health_checks] == ["database", "redis", "ai"]
        assert isinstance(container.job_queue, CeleryJobQueue)
    finally:
        await container.aclose()


def test_unknown_provider_is_rejected_at_startup_with_the_registry_options(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("AI__PROVIDER", "skynet")

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    for provider in AI_PROVIDERS:
        assert provider in str(error.value)


def test_registry_raises_a_clear_error_for_an_unknown_provider() -> None:
    with pytest.raises(UnknownProviderError) as error:
        build_language_model(AiSettings(provider="skynet"), httpx.AsyncClient())

    assert "skynet" in str(error.value)
    assert "fake" in str(error.value)


async def test_a_new_provider_needs_only_a_registry_entry(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    class OtherModel(FakeLanguageModel):
        provider = "other"

    minimal_env.setitem(AI_PROVIDERS, "other", lambda ai, _client: OtherModel(model=ai.model))
    minimal_env.setenv("AI__PROVIDER", "other")
    minimal_env.setenv("AI__API_KEY", TEST_API_KEY)

    container = build_container(load_settings())

    try:
        assert isinstance(container.language_model, OtherModel)
    finally:
        await container.aclose()


@pytest.mark.parametrize(
    ("provider", "adapter"),
    [("openrouter", OpenRouterLanguageModel), ("gemini", GeminiLanguageModel)],
)
async def test_a_real_provider_is_selected_by_configuration_alone(
    minimal_env: pytest.MonkeyPatch, provider: str, adapter: type
) -> None:
    minimal_env.setenv("AI__PROVIDER", provider)
    minimal_env.setenv("AI__MODEL", "some-model")
    minimal_env.setenv("AI__API_KEY", TEST_API_KEY)

    container = build_container(load_settings())

    try:
        assert isinstance(container.language_model, adapter)
        assert container.language_model.provider == provider
        assert container.language_model.model == "some-model"
        assert TEST_API_KEY not in repr(container)
    finally:
        await container.aclose()


@pytest.mark.parametrize("provider", ["openrouter", "gemini"])
def test_a_real_provider_without_a_key_is_rejected_at_startup(
    minimal_env: pytest.MonkeyPatch, provider: str
) -> None:
    minimal_env.setenv("AI__PROVIDER", provider)

    with pytest.raises(ConfigurationError, match="AI__API_KEY"):
        load_settings()


def test_the_registry_refuses_to_build_a_real_provider_without_a_key() -> None:
    """Settings built by hand skip ``load_settings``; the registry still fails clearly."""
    with pytest.raises(ConfigurationError, match="AI__API_KEY"):
        build_language_model(AiSettings(provider="openrouter"), httpx.AsyncClient())


async def test_the_container_owns_one_ai_http_client_and_closes_it(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.setenv("AI__TIMEOUT_SECONDS", "12.5")

    container = build_container(load_settings())

    assert container.ai_http_client.timeout == httpx.Timeout(12.5)
    assert container.ai_http_client.is_closed is False

    await container.aclose()

    assert container.ai_http_client.is_closed is True
