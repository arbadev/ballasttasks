"""Contract every LanguageModel adapter must honour.

Registering a new adapter = one new factory line in ``ADAPTERS``.
"""

from collections.abc import Callable

import pytest

from app.application.ports.language_model import LanguageModel
from app.infrastructure.ai.fake import FakeLanguageModel
from tests.ai_stubs import gemini_happy_path, gemini_over, openrouter_happy_path, openrouter_over

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
