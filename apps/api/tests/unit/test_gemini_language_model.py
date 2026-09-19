"""GeminiLanguageModel against a stubbed transport: the request it sends and how every
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
from app.infrastructure.ai.gemini import GeminiLanguageModel
from tests.ai_stubs import (
    GEMINI_BLOCKED_PROMPT,
    GEMINI_COMPLETION,
    GEMINI_INVALID_KEY,
    GEMINI_MODEL,
    TEST_API_KEY,
    Handler,
    answering,
    gemini_error,
    gemini_happy_path,
    gemini_over,
    raising,
    trickling,
)

GENERATE_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)
MODEL_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}"


def _candidate_with(**fields: Any) -> dict[str, Any]:
    return {**GEMINI_COMPLETION, "candidates": [fields]}


def _not_json(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="<html>Bad gateway</html>")


async def test_generate_posts_the_prompt_to_generate_content_and_returns_the_text() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return gemini_happy_path(request)

    text = await gemini_over(handler).generate("Summarise this task")

    assert text == "Hello there!"
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == GENERATE_URL
    assert request.headers["x-goog-api-key"] == TEST_API_KEY
    assert json.loads(request.content) == {
        "contents": [{"parts": [{"text": "Summarise this task"}]}]
    }


async def test_the_key_travels_in_a_header_never_in_the_url() -> None:
    """The documented ``?key=`` form would put the secret in every logged URL."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return gemini_happy_path(request)

    model = gemini_over(handler)
    await model.generate("hi")
    await model.check()

    assert len(seen) == 2
    assert not [request for request in seen if TEST_API_KEY in str(request.url)]


async def test_the_text_parts_of_the_first_candidate_are_joined() -> None:
    body = _candidate_with(
        content={"parts": [{"text": "Hello "}, {"text": "there!"}], "role": "model"},
        finishReason="STOP",
    )

    assert await gemini_over(answering(200, body)).generate("hi") == "Hello there!"


async def test_a_model_id_may_carry_the_models_prefix() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return gemini_happy_path(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = GeminiLanguageModel(client, model=f"models/{GEMINI_MODEL}", api_key=TEST_API_KEY)

    await model.generate("hi")

    assert str(seen[0].url) == GENERATE_URL


async def test_a_base_url_override_replaces_the_default_host() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return gemini_happy_path(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = GeminiLanguageModel(
        client, model=GEMINI_MODEL, api_key=TEST_API_KEY, base_url="https://proxy.test/v1beta/"
    )

    await model.generate("hi")
    await model.check()

    assert [str(request.url) for request in seen] == [
        f"https://proxy.test/v1beta/models/{GEMINI_MODEL}:generateContent",
        f"https://proxy.test/v1beta/models/{GEMINI_MODEL}",
    ]


def test_describes_itself() -> None:
    model = gemini_over(gemini_happy_path)

    assert (model.provider, model.model) == ("gemini", GEMINI_MODEL)


# Failures of the exchange itself: they hit generate() and check() alike.
EXCHANGE_FAILURES = [
    # Gemini answers a rejected key with 400 INVALID_ARGUMENT, so the status alone is not
    # enough: the adapter has to read ``error.details[].reason``.
    pytest.param(
        answering(400, GEMINI_INVALID_KEY),
        LanguageModelAuthenticationError,
        id="400-api-key-invalid",
    ),
    pytest.param(
        answering(401, gemini_error(401, "UNAUTHENTICATED")),
        LanguageModelAuthenticationError,
        id="401",
    ),
    pytest.param(
        answering(403, gemini_error(403, "PERMISSION_DENIED")),
        LanguageModelAuthenticationError,
        id="403",
    ),
    pytest.param(
        answering(429, gemini_error(429, "RESOURCE_EXHAUSTED")),
        LanguageModelRateLimitedError,
        id="429",
    ),
    pytest.param(
        answering(500, gemini_error(500, "INTERNAL")), LanguageModelUnavailableError, id="500"
    ),
    pytest.param(
        answering(503, gemini_error(503, "UNAVAILABLE")), LanguageModelUnavailableError, id="503"
    ),
    pytest.param(
        answering(504, gemini_error(504, "DEADLINE_EXCEEDED")),
        LanguageModelTimeoutError,
        id="504",
    ),
    pytest.param(
        answering(400, gemini_error(400, "INVALID_ARGUMENT")),
        LanguageModelInvalidResponseError,
        id="400-bad-request",
    ),
    pytest.param(
        answering(404, gemini_error(404, "NOT_FOUND")),
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
]

# A well-formed answer that carries no usable completion: only generate() can see these.
UNUSABLE_COMPLETIONS = [
    pytest.param(answering(200, {}), LanguageModelInvalidResponseError, id="missing-candidates"),
    # Documented: a blocked prompt returns no candidates, only ``promptFeedback``.
    pytest.param(
        answering(200, GEMINI_BLOCKED_PROMPT),
        LanguageModelInvalidResponseError,
        id="prompt-blocked",
    ),
    pytest.param(
        answering(200, _candidate_with(finishReason="SAFETY")),
        LanguageModelInvalidResponseError,
        id="candidate-without-content",
    ),
    pytest.param(
        answering(200, _candidate_with(content={"role": "model"}, finishReason="MAX_TOKENS")),
        LanguageModelInvalidResponseError,
        id="content-without-parts",
    ),
    pytest.param(
        answering(200, _candidate_with(content={"parts": [{"text": " \n"}]}, finishReason="STOP")),
        LanguageModelInvalidResponseError,
        id="blank-text",
    ),
    pytest.param(
        answering(200, _candidate_with(content={"parts": [{"text": 7}]}, finishReason="STOP")),
        LanguageModelInvalidResponseError,
        id="text-not-a-string",
    ),
]


@pytest.mark.parametrize(("handler", "expected"), EXCHANGE_FAILURES + UNUSABLE_COMPLETIONS)
async def test_generate_maps_every_failure_to_a_typed_error(
    handler: Handler, expected: type[LanguageModelError]
) -> None:
    with pytest.raises(LanguageModelError) as error:
        await gemini_over(handler).generate("hi")

    assert type(error.value) is expected
    assert error.value.provider == "gemini"


@pytest.mark.parametrize(("handler", "expected"), EXCHANGE_FAILURES)
async def test_check_is_false_rather_than_raising(
    handler: Handler, expected: type[LanguageModelError]
) -> None:
    assert await gemini_over(handler).check() is False


async def test_check_reads_the_free_model_resource_and_never_generates() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return gemini_happy_path(request)

    assert await gemini_over(handler).check() is True

    (request,) = seen
    assert request.method == "GET"
    assert str(request.url) == MODEL_URL
    assert request.headers["x-goog-api-key"] == TEST_API_KEY
    assert request.extensions["timeout"]["read"] == 2.0


async def test_one_connection_error_is_retried_once() -> None:
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ConnectError("simulated", request=request)
        return gemini_happy_path(request)

    assert await gemini_over(handler).generate("hi") == "Hello there!"
    assert len(attempts) == 2


async def test_the_timeout_is_a_total_deadline_not_a_per_read_one() -> None:
    """Each chunk arrives well inside the timeout; the whole answer takes four times as long."""
    handler = trickling(GEMINI_COMPLETION, chunks=20, seconds_between_chunks=0.02)

    with pytest.raises(LanguageModelTimeoutError):
        await gemini_over(handler, timeout_seconds=0.1).generate("hi")


def _echoing_the_key(request: httpx.Request) -> httpx.Response:
    """A hostile or careless provider that repeats the credential in its error body."""
    body = gemini_error(400, "INVALID_ARGUMENT", f"API key not valid: {TEST_API_KEY}")
    return httpx.Response(400, json=body)


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(answering(400, GEMINI_INVALID_KEY), id="rejected-key"),
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
    model = gemini_over(handler)

    with pytest.raises(LanguageModelError) as error:
        await model.generate("hi")
    assert await model.check() is False

    chain: list[BaseException] = [error.value]
    while chain[-1].__cause__ is not None:
        chain.append(chain[-1].__cause__)
    shown = [caplog.text, repr(model)]
    shown += [text for link in chain for text in (str(link), repr(link))]
    assert not [text for text in shown if TEST_API_KEY in text]
