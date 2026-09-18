import pytest

from app.bootstrap import Container, build_container, load_settings
from app.infrastructure.ai.fake import FakeLanguageModel
from app.infrastructure.ai.registry import AI_PROVIDERS, UnknownProviderError, build_language_model
from app.infrastructure.config.settings import AiSettings, ConfigurationError
from app.infrastructure.jobs.queue import CeleryJobQueue


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
        build_language_model(AiSettings(provider="skynet"))

    assert "skynet" in str(error.value)
    assert "fake" in str(error.value)


async def test_a_new_provider_needs_only_a_registry_entry(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    class OtherModel(FakeLanguageModel):
        provider = "other"

    minimal_env.setitem(AI_PROVIDERS, "other", lambda ai: OtherModel(model=ai.model))  # type: ignore[arg-type]
    minimal_env.setenv("AI__PROVIDER", "other")

    container = build_container(load_settings())

    try:
        assert isinstance(container.language_model, OtherModel)
    finally:
        await container.aclose()
