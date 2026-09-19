"""Opt-in checks against the real providers: ``uv run pytest -m live``.

Deselected by default and never part of the integration suite. They spend a few tokens,
so each one runs only when ``AI__PROVIDER`` names its provider and ``AI__API_KEY`` holds a
real key (``AI__MODEL`` and ``AI__BASE_URL`` are honoured too); otherwise it is skipped.
"""

import os
from collections.abc import AsyncIterator

import httpx
import pytest

from app.application.ports.language_model import LanguageModel
from app.infrastructure.ai.registry import build_language_model
from app.infrastructure.config.settings import AiSettings

pytestmark = pytest.mark.live

DEFAULT_MODELS = {"openrouter": "google/gemini-3.8-flash", "gemini": "gemini-3.8-flash"}


@pytest.fixture(params=sorted(DEFAULT_MODELS))
async def live_model(request: pytest.FixtureRequest) -> AsyncIterator[LanguageModel]:
    provider: str = request.param
    if not os.environ.get("AI__API_KEY", "").strip():
        pytest.skip(f"AI__API_KEY is not set: the live {provider} test needs a real key")
    if os.environ.get("AI__PROVIDER") != provider:
        pytest.skip(f"AI__PROVIDER is not {provider!r}: the key belongs to another provider")
    ai = AiSettings(
        provider=provider,
        model=os.environ.get("AI__MODEL", DEFAULT_MODELS[provider]),
        api_key=os.environ["AI__API_KEY"],
        base_url=os.environ.get("AI__BASE_URL") or None,
    )
    async with httpx.AsyncClient(timeout=ai.timeout_seconds) as client:
        yield build_language_model(ai, client)


async def test_the_real_provider_accepts_the_key_and_generates_text(
    live_model: LanguageModel,
) -> None:
    assert await live_model.check() is True

    text = await live_model.generate("Reply with the single word: pong")

    assert text.strip()
