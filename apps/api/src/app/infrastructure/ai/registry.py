"""Provider name -> LanguageModel factory.

Adding a provider: write the adapter, make it pass
``tests/contract/test_language_model_contract.py``, then add ONE line to ``AI_PROVIDERS``.
Settings validation (fed by the composition root) and ``build_language_model`` read this mapping.
"""

from collections.abc import Callable

from app.application.ports.language_model import LanguageModel
from app.infrastructure.ai.fake import FakeLanguageModel
from app.infrastructure.config.settings import AiSettings

LanguageModelFactory = Callable[[AiSettings], LanguageModel]

AI_PROVIDERS: dict[str, LanguageModelFactory] = {
    "fake": lambda ai: FakeLanguageModel(model=ai.model),
}


class UnknownProviderError(LookupError):
    def __init__(self, provider: str) -> None:
        options = ", ".join(sorted(AI_PROVIDERS))
        super().__init__(f"Unknown AI provider {provider!r}. Valid options: {options}")


def build_language_model(ai: AiSettings) -> LanguageModel:
    try:
        factory = AI_PROVIDERS[ai.provider]
    except KeyError:
        raise UnknownProviderError(ai.provider) from None
    return factory(ai)
