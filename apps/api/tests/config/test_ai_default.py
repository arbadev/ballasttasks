"""Production default is real; offline callers must deliberately select fake."""

import httpx
import pytest

from app.bootstrap import build_container, load_settings
from app.infrastructure.ai.openrouter import OpenRouterLanguageModel
from app.infrastructure.ai.registry import build_language_model
from app.infrastructure.config.settings import AiSettings, ConfigurationError
from tests.ai_stubs import TEST_API_KEY


def test_normal_ai_settings_preserve_the_requested_alias() -> None:
    ai = AiSettings()
    assert ai.provider == "openrouter"
    assert ai.model == "~openai/gpt-luna-latest"
    assert ai.base_url is None


async def test_normal_startup_requires_a_key_without_offline_fallback(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.delenv("AI__PROVIDER", raising=False)
    minimal_env.delenv("AI__MODEL", raising=False)
    settings = load_settings()
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConfigurationError, match="AI__API_KEY"):
            build_language_model(settings.ai, client)


async def test_normal_startup_with_key_selects_openrouter(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    minimal_env.delenv("AI__PROVIDER", raising=False)
    minimal_env.delenv("AI__MODEL", raising=False)
    minimal_env.setenv("AI__API_KEY", TEST_API_KEY)
    container = build_container(load_settings())
    try:
        assert isinstance(container.language_model, OpenRouterLanguageModel)
        assert container.language_model.model == "~openai/gpt-luna-latest"
    finally:
        await container.aclose()
