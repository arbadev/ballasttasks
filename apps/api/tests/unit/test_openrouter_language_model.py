"""OpenRouterLanguageModel against a stubbed transport: the request it sends and how every
provider failure becomes one of the port's typed errors. Nothing here touches the network."""

import json
import logging
from typing import Any

import httpx
import pytest

from app.application.ports.language_model import (
    LanguageModelAuthenticationError,
    LanguageModelError,
    LanguageModelInvalidResponseError,
    LanguageModelRateLimitedError,
    LanguageModelTimeoutError,
    LanguageModelUnavailableError,
)
from app.infrastructure.ai.openrouter import OpenRouterLanguageModel
from tests.ai_stubs import (
    OPENROUTER_COMPLETION,
    OPENROUTER_GUARDRAIL_METADATA,
    OPENROUTER_MODEL,
    OPENROUTER_MODERATION_METADATA,
    TEST_API_KEY,
    Handler,
    answering,
    openrouter_error,
    openrouter_happy_path,
    openrouter_over,
    raising,
    trickling,
)


def _completion_with(**message: Any) -> dict[str, Any]:
    choice = {**OPENROUTER_COMPLETION["choices"][0], "message": message}
    return {**OPENROUTER_COMPLETION, "choices": [choice]}


def _not_json(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="<html>Bad gateway</html>")


async def test_generate_posts_the_prompt_as_a_chat_completion_and_returns_the_text() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return openrouter_happy_path(request)

    text = await openrouter_over(handler).generate("Summarise this task")

    assert text == "Hello there!"
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {TEST_API_KEY}"
    assert json.loads(request.content) == {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": "Summarise this task"}],
    }


async def test_a_base_url_override_replaces_the_default_host() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return openrouter_happy_path(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenRouterLanguageModel(
        client, model=OPENROUTER_MODEL, api_key=TEST_API_KEY, base_url="https://proxy.test/v1/"
    )

    await model.generate("hi")
    await model.check()

    assert [str(request.url) for request in seen] == [
        "https://proxy.test/v1/chat/completions",
        "https://proxy.test/v1/key",
    ]


def test_describes_itself() -> None:
    model = openrouter_over(openrouter_happy_path)

    assert (model.provider, model.model) == ("openrouter", OPENROUTER_MODEL)


# Failures of the exchange itself: they hit generate() and check() alike.
EXCHANGE_FAILURES = [
    # 401 body: the documented example for GET /key, which is also what a request with a
    # bearer value that is not key-shaped gets back.
    pytest.param(
        answering(401, openrouter_error(401, "Missing Authentication header")),
        LanguageModelAuthenticationError,
        id="401",
    ),
    # A bare 403 is about the key; with moderation or guardrail metadata it is about the prompt.
    pytest.param(
        answering(403, openrouter_error(403)), LanguageModelAuthenticationError, id="403-bare"
    ),
    pytest.param(
        answering(403, openrouter_error(403, metadata={"provider_name": "OpenAI"})),
        LanguageModelAuthenticationError,
        id="403-with-unrelated-metadata",
    ),
    pytest.param(
        answering(403, openrouter_error(403, metadata=OPENROUTER_MODERATION_METADATA)),
        LanguageModelInvalidResponseError,
        id="403-moderation-flag",
    ),
    pytest.param(
        answering(403, openrouter_error(403, metadata=OPENROUTER_GUARDRAIL_METADATA)),
        LanguageModelInvalidResponseError,
        id="403-guardrail-block",
    ),
    pytest.param(
        answering(401, openrouter_error(401, metadata=OPENROUTER_MODERATION_METADATA)),
        LanguageModelAuthenticationError,
        id="401-is-never-a-blocked-prompt",
    ),
    pytest.param(answering(429, openrouter_error(429)), LanguageModelRateLimitedError, id="429"),
    pytest.param(answering(408, openrouter_error(408)), LanguageModelTimeoutError, id="408"),
    pytest.param(
        answering(402, openrouter_error(402)), LanguageModelUnavailableError, id="402-no-credits"
    ),
    pytest.param(answering(500, openrouter_error(500)), LanguageModelUnavailableError, id="500"),
    pytest.param(answering(502, openrouter_error(502)), LanguageModelUnavailableError, id="502"),
    pytest.param(answering(503, openrouter_error(503)), LanguageModelUnavailableError, id="503"),
    pytest.param(
        answering(404, openrouter_error(404, "No endpoints found")),
        LanguageModelInvalidResponseError,
        id="404-unknown-model",
    ),
    pytest.param(raising(httpx.ReadTimeout), LanguageModelTimeoutError, id="read-timeout"),
    pytest.param(raising(httpx.ConnectTimeout), LanguageModelTimeoutError, id="connect-timeout"),
    pytest.param(raising(httpx.ConnectError), LanguageModelUnavailableError, id="connect-error"),
    pytest.param(raising(httpx.ReadError), LanguageModelUnavailableError, id="read-error"),
    pytest.param(_not_json, LanguageModelInvalidResponseError, id="malformed-json"),
    pytest.param(
        answering(200, ["not", "an", "object"]),
        LanguageModelInvalidResponseError,
        id="json-not-an-object",
    ),
    # Documented: an error can arrive with HTTP 200; ``error.code`` then carries the status.
    pytest.param(
        answering(200, openrouter_error(429, "Rate limit exceeded")),
        LanguageModelRateLimitedError,
        id="200-with-error-429",
    ),
    pytest.param(
        answering(200, openrouter_error(403)),
        LanguageModelAuthenticationError,
        id="200-with-error-403-bare",
    ),
    pytest.param(
        answering(200, openrouter_error(403, metadata=OPENROUTER_MODERATION_METADATA)),
        LanguageModelInvalidResponseError,
        id="200-with-error-403-moderation-flag",
    ),
    pytest.param(
        answering(200, openrouter_error(403, metadata=OPENROUTER_GUARDRAIL_METADATA)),
        LanguageModelInvalidResponseError,
        id="200-with-error-403-guardrail-block",
    ),
    pytest.param(
        answering(200, {"error": {"message": "no code"}}),
        LanguageModelInvalidResponseError,
        id="200-with-error-without-code",
    ),
]

# A well-formed answer that carries no usable completion: only generate() can see these.
UNUSABLE_COMPLETIONS = [
    pytest.param(answering(200, {}), LanguageModelInvalidResponseError, id="missing-choices"),
    pytest.param(
        answering(200, {**OPENROUTER_COMPLETION, "choices": []}),
        LanguageModelInvalidResponseError,
        id="no-choices",
    ),
    pytest.param(
        answering(200, _completion_with(role="assistant")),
        LanguageModelInvalidResponseError,
        id="missing-content",
    ),
    pytest.param(
        answering(200, _completion_with(role="assistant", content=None)),
        LanguageModelInvalidResponseError,
        id="null-content",
    ),
    pytest.param(
        answering(200, _completion_with(role="assistant", content="  \n")),
        LanguageModelInvalidResponseError,
        id="blank-content",
    ),
]


@pytest.mark.parametrize(("handler", "expected"), EXCHANGE_FAILURES + UNUSABLE_COMPLETIONS)
async def test_generate_maps_every_failure_to_a_typed_error(
    handler: Handler, expected: type[LanguageModelError]
) -> None:
    with pytest.raises(LanguageModelError) as error:
        await openrouter_over(handler).generate("hi")

    assert type(error.value) is expected
    assert error.value.provider == "openrouter"


@pytest.mark.parametrize(("handler", "expected"), EXCHANGE_FAILURES)
async def test_check_is_false_rather_than_raising(
    handler: Handler, expected: type[LanguageModelError]
) -> None:
    assert await openrouter_over(handler).check() is False


async def test_check_asks_the_free_key_endpoint_and_never_generates() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return openrouter_happy_path(request)

    assert await openrouter_over(handler).check() is True

    (request,) = seen
    assert request.method == "GET"
    assert str(request.url) == "https://openrouter.ai/api/v1/key"
    assert request.headers["Authorization"] == f"Bearer {TEST_API_KEY}"
    assert request.extensions["timeout"]["read"] == 2.0


async def test_one_connection_error_is_retried_once() -> None:
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ConnectError("simulated", request=request)
        return openrouter_happy_path(request)

    assert await openrouter_over(handler).generate("hi") == "Hello there!"
    assert len(attempts) == 2


async def test_the_retry_is_bounded_to_one() -> None:
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError("simulated", request=request)

    with pytest.raises(LanguageModelUnavailableError):
        await openrouter_over(handler).generate("hi")

    assert len(attempts) == 2


async def test_a_request_that_may_have_reached_the_provider_is_not_retried() -> None:
    """A read timeout can follow a completed (billed) generation: never send it twice."""
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ReadTimeout("simulated", request=request)

    with pytest.raises(LanguageModelTimeoutError):
        await openrouter_over(handler).generate("hi")

    assert len(attempts) == 1


async def test_the_timeout_is_a_total_deadline_not_a_per_read_one() -> None:
    """Each chunk arrives well inside the timeout; the whole answer takes four times as long."""
    handler = trickling(OPENROUTER_COMPLETION, chunks=20, seconds_between_chunks=0.02)

    with pytest.raises(LanguageModelTimeoutError):
        await openrouter_over(handler, timeout_seconds=0.1).generate("hi")


async def test_a_slow_answer_inside_the_deadline_is_still_returned() -> None:
    handler = trickling(OPENROUTER_COMPLETION, chunks=3, seconds_between_chunks=0.01)

    assert await openrouter_over(handler, timeout_seconds=5.0).generate("hi") == "Hello there!"


async def test_a_blocked_prompt_never_shows_the_flagged_input() -> None:
    body = openrouter_error(403, metadata=OPENROUTER_MODERATION_METADATA)

    with pytest.raises(LanguageModelInvalidResponseError) as error:
        await openrouter_over(answering(403, body)).generate("hi")

    assert OPENROUTER_MODERATION_METADATA["flagged_input"] not in str(error.value)


def _echoing_the_key(request: httpx.Request) -> httpx.Response:
    """A hostile or careless provider that repeats the credential in its error body."""
    return httpx.Response(401, json=openrouter_error(401, f"Invalid key {TEST_API_KEY}"))


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(_echoing_the_key, id="rejected-key-echoed-back"),
        pytest.param(raising(httpx.ConnectError), id="connect-error"),
        pytest.param(raising(httpx.ReadTimeout), id="timeout"),
        pytest.param(_not_json, id="malformed-json"),
    ],
)
async def test_the_api_key_never_appears_in_an_error_or_a_log_line(
    handler: Handler, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    model = openrouter_over(handler)

    with pytest.raises(LanguageModelError) as error:
        await model.generate("hi")
    assert await model.check() is False

    chain: list[BaseException] = [error.value]
    while chain[-1].__cause__ is not None:
        chain.append(chain[-1].__cause__)
    shown = [caplog.text, repr(model)]
    shown += [text for link in chain for text in (str(link), repr(link))]
    assert not [text for text in shown if TEST_API_KEY in text]
