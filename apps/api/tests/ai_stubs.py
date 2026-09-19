"""Offline stand-ins for the AI providers: ``httpx.MockTransport`` plus documented bodies.

The response shapes are copied from each provider's official reference (read 2026-09-18),
so no test here needs the network or an API key:

- OpenRouter: https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion,
  https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key and
  https://openrouter.ai/docs/api_reference/errors-and-debugging
- Gemini: https://ai.google.dev/api/generate-content and https://ai.google.dev/api/models
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

import httpx

from app.infrastructure.ai.gemini import GeminiLanguageModel
from app.infrastructure.ai.openrouter import OpenRouterLanguageModel

Handler = (
    Callable[[httpx.Request], httpx.Response]
    | Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]
)

# Shaped like a real key so a leak is recognisable, but it opens nothing.
TEST_API_KEY = "sk-test-0123456789abcdef-never-a-real-key"

OPENROUTER_MODEL = "google/gemini-3.8-flash"
GEMINI_MODEL = "gemini-3.8-flash"

OPENROUTER_COMPLETION: dict[str, Any] = {
    "id": "gen-xxxxxxxxxxxxxx",
    "choices": [
        {
            "finish_reason": "stop",
            "native_finish_reason": "stop",
            "message": {"role": "assistant", "content": "Hello there!"},
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14, "cost": 0.00014},
    "model": OPENROUTER_MODEL,
}

# GET /key: only the fields the documented example leads with; the adapter reads none of them.
OPENROUTER_KEY_INFO: dict[str, Any] = {
    "data": {
        "label": "sk-or-v1-au7...890",
        "limit": 100,
        "limit_remaining": 74.5,
        "usage": 25.5,
        "is_free_tier": False,
    }
}

GEMINI_COMPLETION: dict[str, Any] = {
    "candidates": [
        {
            "content": {"parts": [{"text": "Hello there!"}], "role": "model"},
            "finishReason": "STOP",
            "index": 0,
        }
    ],
    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4, "totalTokenCount": 14},
    "modelVersion": GEMINI_MODEL,
    "responseId": "response-xxxxxxxx",
}

GEMINI_MODEL_INFO: dict[str, Any] = {
    "name": f"models/{GEMINI_MODEL}",
    "version": "001",
    "displayName": "Gemini 3.8 Flash",
    "inputTokenLimit": 1048576,
    "outputTokenLimit": 65536,
    "supportedGenerationMethods": ["generateContent", "countTokens"],
}

# What the API really answers to a rejected key: HTTP 400, not 401 (observed 2026-09-18
# with a dummy key against GET /v1beta/models/{model}).
GEMINI_INVALID_KEY: dict[str, Any] = {
    "error": {
        "code": 400,
        "message": "API key not valid. Please pass a valid API key.",
        "status": "INVALID_ARGUMENT",
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": "API_KEY_INVALID",
                "domain": "googleapis.com",
                "metadata": {"service": "generativelanguage.googleapis.com"},
            }
        ],
    }
}


# A blocked prompt, as each provider documents it. OpenRouter answers 403 with the
# moderation or guardrail details in ``error.metadata``; Gemini answers 200 with no
# candidates, only ``promptFeedback``.
OPENROUTER_MODERATION_METADATA: dict[str, Any] = {
    "reasons": ["violence"],
    "flagged_input": "the offending part of the prompt...",
    "provider_name": "OpenAI",
    "model_slug": "openai/gpt-5",
}
OPENROUTER_GUARDRAIL_METADATA: dict[str, Any] = {"patterns": ["credit-card-number"]}
GEMINI_BLOCKED_PROMPT: dict[str, Any] = {"promptFeedback": {"blockReason": "SAFETY"}}


def openrouter_error(
    code: int, message: str = "provider said no", metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """OpenRouter's documented ``ErrorResponse``."""
    error: dict[str, Any] = {"code": code, "message": message}
    if metadata is not None:
        error["metadata"] = metadata
    return {"error": error}


def gemini_error(code: int, status: str, message: str = "provider said no") -> dict[str, Any]:
    """Google's ``google.rpc.Status`` error envelope."""
    return {"error": {"code": code, "message": message, "status": status}}


def answering(status_code: int, body: object) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    return handler


def trickling(body: object, *, chunks: int, seconds_between_chunks: float) -> Handler:
    """A complete, valid answer that arrives slowly: every read is quick, the whole is not."""
    content = json.dumps(body).encode()
    size = -(-len(content) // chunks)

    async def stream() -> AsyncIterator[bytes]:
        for start in range(0, len(content), size):
            await asyncio.sleep(seconds_between_chunks)
            yield content[start : start + size]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=stream())

    return handler


def raising(error: type[httpx.TransportError]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error("simulated transport failure", request=request)

    return handler


def openrouter_happy_path(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/key"):
        return httpx.Response(200, json=OPENROUTER_KEY_INFO)
    return httpx.Response(200, json=OPENROUTER_COMPLETION)


def gemini_happy_path(request: httpx.Request) -> httpx.Response:
    if request.method == "GET":
        return httpx.Response(200, json=GEMINI_MODEL_INFO)
    return httpx.Response(200, json=GEMINI_COMPLETION)


def openrouter_over(handler: Handler, *, timeout_seconds: float = 5.0) -> OpenRouterLanguageModel:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout_seconds)
    return OpenRouterLanguageModel(client, model=OPENROUTER_MODEL, api_key=TEST_API_KEY)


def gemini_over(handler: Handler, *, timeout_seconds: float = 5.0) -> GeminiLanguageModel:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout_seconds)
    return GeminiLanguageModel(client, model=GEMINI_MODEL, api_key=TEST_API_KEY)
