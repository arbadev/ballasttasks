"""LanguageModel over the Gemini API's ``generateContent`` (https://ai.google.dev/api/generate-content).

``generateContent`` is the endpoint Google recommends for stable deployments; the newer
Interactions API is still in beta. ``check`` reads the model resource (``GET models/{id}``):
it costs nothing and proves the key and the model id in one call.

The key travels in the ``x-goog-api-key`` header, never as the ``?key=`` query parameter,
so it cannot end up in a logged URL.
"""

from typing import Any, ClassVar

import httpx

from app.application.ports.language_model import (
    LanguageModelAuthenticationError,
    LanguageModelInvalidResponseError,
)
from app.infrastructure.ai.http import CHECK_TIMEOUT_SECONDS, json_object, send

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiLanguageModel:
    provider: ClassVar[str] = "gemini"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
    ) -> None:
        self.model = model.removeprefix("models/")
        self._client = client
        self._model_url = f"{(base_url or DEFAULT_BASE_URL).rstrip('/')}/models/{self.model}"
        self._headers = {"x-goog-api-key": api_key}

    def __repr__(self) -> str:
        return f"{type(self).__name__}(model={self.model!r})"

    async def generate(self, prompt: str) -> str:
        body = await self._exchange(
            "POST",
            f"{self._model_url}:generateContent",
            json={"contents": [{"parts": [{"text": prompt}]}]},
        )
        try:
            # No candidates at all means the prompt was blocked (see ``promptFeedback``).
            parts = body["candidates"][0]["content"]["parts"]
            text = "".join(part["text"] for part in parts if "text" in part)
        except KeyError, IndexError, TypeError:
            raise self._invalid("no completion in the response") from None
        if not text.strip():
            raise self._invalid("empty completion")
        return text

    async def check(self) -> bool:
        try:
            await self._exchange("GET", self._model_url, timeout_seconds=CHECK_TIMEOUT_SECONDS)
        except Exception:
            return False
        return True

    async def _exchange(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        response = await send(
            self._client,
            self.provider,
            method,
            url,
            headers=self._headers,
            json=json,
            timeout_seconds=timeout_seconds,
        )
        if response.status_code == 400 and _rejects_the_key(response):
            raise LanguageModelAuthenticationError(self.provider, "HTTP 400 (API key not valid)")
        return json_object(self.provider, response)

    def _invalid(self, reason: str) -> LanguageModelInvalidResponseError:
        return LanguageModelInvalidResponseError(self.provider, reason)


def _rejects_the_key(response: httpx.Response) -> bool:
    """Gemini answers a bad key with 400 INVALID_ARGUMENT; only ``details`` tells it apart."""
    try:
        details = response.json()["error"]["details"]
        return any(detail.get("reason") == "API_KEY_INVALID" for detail in details)
    except ValueError, KeyError, TypeError, AttributeError:
        return False
