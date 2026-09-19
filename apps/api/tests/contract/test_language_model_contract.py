"""Contract every LanguageModel adapter must honour.

Registering a new adapter = one new factory line in ``ADAPTERS``.
"""

from collections.abc import Callable

import pytest

from app.application.ports.language_model import (
    LanguageModel,
    LanguageModelError,
    LanguageModelInvalidResponseError,
)
from app.infrastructure.ai.fake import FakeLanguageModel
from tests.ai_stubs import (
    GEMINI_BLOCKED_PROMPT,
    OPENROUTER_GUARDRAIL_METADATA,
    OPENROUTER_MODERATION_METADATA,
    answering,
    gemini_happy_path,
    gemini_over,
    openrouter_error,
    openrouter_happy_path,
    openrouter_over,
)

AdapterFactory = Callable[[], LanguageModel]

ADAPTERS = [
    pytest.param(lambda: FakeLanguageModel(model="fake-1"), id="fake"),
    pytest.param(lambda: openrouter_over(openrouter_happy_path), id="openrouter"),
    pytest.param(lambda: gemini_over(gemini_happy_path), id="gemini"),
]


@pytest.mark.parametrize("factory", ADAPTERS)
async def test_generate_returns_a_non_empty_string(factory: AdapterFactory) -> None:
    text = await factory().generate("Summarise this task")

    assert isinstance(text, str)
    assert text.strip()


@pytest.mark.parametrize("factory", ADAPTERS)
async def test_check_returns_a_bool(factory: AdapterFactory) -> None:
    assert isinstance(await factory().check(), bool)


@pytest.mark.parametrize("factory", ADAPTERS)
def test_provider_and_model_are_non_empty(factory: AdapterFactory) -> None:
    model = factory()

    assert isinstance(model.provider, str)
    assert model.provider
    assert isinstance(model.model, str)
    assert model.model


# The same event, as each provider reports it. An adapter whose provider can refuse a prompt
# adds its documented refusal here; ``fake`` never refuses.
BLOCKED_PROMPTS = [
    pytest.param(
        lambda: openrouter_over(
            answering(403, openrouter_error(403, metadata=OPENROUTER_MODERATION_METADATA))
        ),
        id="openrouter-moderation-flag",
    ),
    pytest.param(
        lambda: openrouter_over(
            answering(403, openrouter_error(403, metadata=OPENROUTER_GUARDRAIL_METADATA))
        ),
        id="openrouter-guardrail-block",
    ),
    pytest.param(
        lambda: openrouter_over(
            answering(200, openrouter_error(403, metadata=OPENROUTER_MODERATION_METADATA))
        ),
        id="openrouter-moderation-flag-in-a-200",
    ),
    pytest.param(lambda: gemini_over(answering(200, GEMINI_BLOCKED_PROMPT)), id="gemini"),
]


@pytest.mark.parametrize("factory", BLOCKED_PROMPTS)
async def test_a_blocked_prompt_is_the_same_error_from_every_provider(
    factory: AdapterFactory,
) -> None:
    with pytest.raises(LanguageModelError) as error:
        await factory().generate("a prompt the provider refuses")

    assert type(error.value) is LanguageModelInvalidResponseError
