"""Provider name -> LanguageModel factory.

Adding a provider: write the adapter, make it pass
``tests/contract/test_language_model_contract.py``, then add ONE line to ``AI_PROVIDERS``.
Settings validation (fed by the composition root) and ``build_language_model`` read this mapping.
"""

from collections.abc import Callable
from typing import Protocol

import httpx

from app.application.ports.language_model import LanguageModel
from app.infrastructure.ai.fake import FakeLanguageModel
from app.infrastructure.ai.gemini import GeminiLanguageModel
from app.infrastructure.ai.openrouter import OpenRouterLanguageModel
from app.infrastructure.config.settings import AiSettings, ConfigurationError

# The client is created and closed by the composition root; a factory only borrows it.
LanguageModelFactory = Callable[[AiSettings, httpx.AsyncClient], LanguageModel]


class _HttpAdapter(Protocol):
    def __call__(
        self, client: httpx.AsyncClient, *, model: str, api_key: str, base_url: str | None
    ) -> LanguageModel: ...


def _over_http(adapter: _HttpAdapter) -> LanguageModelFactory:
    """Factory for an adapter that talks HTTP with an API key."""

    def factory(ai: AiSettings, client: httpx.AsyncClient) -> LanguageModel:
        if ai.api_key is None:
            raise ConfigurationError(f"AI__API_KEY is required when AI__PROVIDER={ai.provider!r}")
        return adapter(
            client,
            model=ai.model,
            api_key=ai.api_key.get_secret_value(),
            base_url=ai.base_url,
        )

    return factory


AI_PROVIDERS: dict[str, LanguageModelFactory] = {
    "fake": lambda ai, _client: FakeLanguageModel(model=ai.model),
    "openrouter": _over_http(OpenRouterLanguageModel),
    "gemini": _over_http(GeminiLanguageModel),
}


class UnknownProviderError(LookupError):
    def __init__(self, provider: str) -> None:
        options = ", ".join(sorted(AI_PROVIDERS))
        super().__init__(f"Unknown AI provider {provider!r}. Valid options: {options}")


def build_language_model(ai: AiSettings, client: httpx.AsyncClient) -> LanguageModel:
    try:
        factory = AI_PROVIDERS[ai.provider]
    except KeyError:
        raise UnknownProviderError(ai.provider) from None
    return factory(ai, client)
