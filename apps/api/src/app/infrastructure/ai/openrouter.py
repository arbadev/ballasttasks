"""LanguageModel over OpenRouter's HTTP API (https://openrouter.ai/docs/api-reference/overview).

``generate`` is one non-streaming chat completion. ``check`` reads ``GET /key``: it costs
nothing and, unlike the public models listing, it fails when the key is rejected.
"""

from typing import Any, ClassVar

import httpx

from app.application.ports.language_model import LanguageModelInvalidResponseError
from app.infrastructure.ai.http import CHECK_TIMEOUT_SECONDS, error_for_status, json_object, send

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
# ``error.metadata`` of a moderation flag (``reasons``, ``flagged_input``) or a guardrail
# block (``patterns``): https://openrouter.ai/docs/api_reference/errors-and-debugging
_BLOCKED_PROMPT_METADATA = frozenset({"reasons", "flagged_input", "patterns"})


class OpenRouterLanguageModel:
    provider: ClassVar[str] = "openrouter"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self._client = client
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def __repr__(self) -> str:
        return f"{type(self).__name__}(model={self.model!r})"

    async def generate(self, prompt: str) -> str:
        body = await self._exchange(
            "POST",
            "/chat/completions",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "reasoning": {"enabled": True},
            },
        )
        try:
            # The port returns final text only. Opaque reasoning_details are not task
            # content, and independent generations must never reuse assistant messages.
            text = body["choices"][0]["message"]["content"]
        except KeyError, IndexError, TypeError:
            raise self._invalid("no completion in the response") from None
        if not isinstance(text, str) or not text.strip():
            raise self._invalid("empty completion")
        return text

    async def check(self) -> bool:
        try:
            await self._exchange("GET", "/key", timeout_seconds=CHECK_TIMEOUT_SECONDS)
        except Exception:
            return False
        return True

    async def _exchange(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        response = await send(
            self._client,
            self.provider,
            method,
            f"{self._base_url}{path}",
            headers=self._headers,
            json=json,
            timeout_seconds=timeout_seconds,
        )
        if _blocks_the_prompt(response):
            raise self._invalid("HTTP 403 (prompt blocked)")
        body = json_object(self.provider, response)
        if "error" in body:
            # Documented: a failure can arrive with HTTP 200, the status in ``error.code``.
            raise self._error_in(body["error"])
        return body

    def _error_in(self, error: object) -> Exception:
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, int) and not isinstance(code, bool):
            return error_for_status(self.provider, code)
        return self._invalid("error without a status code")

    def _invalid(self, reason: str) -> LanguageModelInvalidResponseError:
        return LanguageModelInvalidResponseError(self.provider, reason)


def _blocks_the_prompt(response: httpx.Response) -> bool:
    """OpenRouter's 403 is a refused key or a refused prompt; only ``metadata`` tells them apart."""
    try:
        error = response.json()["error"]
        status = error["code"] if response.is_success else response.status_code
        metadata = error["metadata"]
    except ValueError, KeyError, TypeError:
        return False
    return (
        status == 403
        and isinstance(metadata, dict)
        and not _BLOCKED_PROMPT_METADATA.isdisjoint(metadata)
    )
