"""What the HTTP-based LanguageModel adapters share: the client, and the translation of
transport failures, HTTP statuses and unreadable bodies into the port's typed errors.

Secrets: an error built here carries a status code or a fixed phrase, never a header, a
URL query or a response body, so a provider that echoes the key back cannot leak it.
"""

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

from app.application.ports.language_model import (
    LanguageModelAuthenticationError,
    LanguageModelError,
    LanguageModelInvalidResponseError,
    LanguageModelRateLimitedError,
    LanguageModelTimeoutError,
    LanguageModelUnavailableError,
)

# check() backs GET /health/ready, which is polled: fail quickly rather than hold it up.
CHECK_TIMEOUT_SECONDS = 2.0

_AUTHENTICATION = frozenset({401, 403})
_RATE_LIMITED = frozenset({429})
# 408 and 504 are the providers' own timeouts; 524 is the CDN giving up on the origin.
_TIMEOUT = frozenset({408, 504, 524})
# 402 (OpenRouter: out of credits) is not the caller's bug: nothing can be served for now.
_UNAVAILABLE = frozenset({402})


def create_http_client(*, timeout_seconds: float) -> httpx.AsyncClient:
    """The one client an adapter shares across calls; whoever creates it closes it.

    ``timeout_seconds`` bounds each phase of a request here and, in ``send``, the whole of it.
    """
    return httpx.AsyncClient(timeout=timeout_seconds)


def _deadline_seconds(timeout: httpx.Timeout) -> float | None:
    """The longest phase the client allows is also all the time one exchange may take."""
    phases = [timeout.connect, timeout.read, timeout.write, timeout.pool]
    return max((phase for phase in phases if phase is not None), default=None)


def error_for_status(provider: str, status: int) -> LanguageModelError:
    reason = f"HTTP {status}"
    if status in _AUTHENTICATION:
        return LanguageModelAuthenticationError(provider, reason)
    if status in _RATE_LIMITED:
        return LanguageModelRateLimitedError(provider, reason)
    if status in _TIMEOUT:
        return LanguageModelTimeoutError(provider, reason)
    if status in _UNAVAILABLE or status >= 500:
        return LanguageModelUnavailableError(provider, reason)
    return LanguageModelInvalidResponseError(provider, f"unexpected {reason}")


async def send(
    client: httpx.AsyncClient,
    provider: str,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    json: Mapping[str, Any] | None = None,
    timeout_seconds: float | None = None,
) -> httpx.Response:
    """Send one request; a transport failure becomes a typed error.

    One bounded retry, and only when the connection was never made: the request cannot
    have reached the provider, so it cannot be billed twice. Anything later is not retried.

    The timeout is a total deadline, retry and body included: httpx alone bounds each phase,
    so a response that trickles in would otherwise outlive it.
    """
    timeout = httpx.USE_CLIENT_DEFAULT if timeout_seconds is None else timeout_seconds
    deadline = _deadline_seconds(client.timeout) if timeout_seconds is None else timeout_seconds

    async def attempt() -> httpx.Response:
        return await client.request(method, url, headers=headers, json=json, timeout=timeout)

    try:
        async with asyncio.timeout(deadline):
            try:
                return await attempt()
            except httpx.ConnectError:
                return await attempt()
    except (TimeoutError, httpx.TimeoutException) as error:
        raise LanguageModelTimeoutError(provider, "request timed out") from error
    except httpx.ConnectError as error:
        raise LanguageModelUnavailableError(provider, "connection failed") from error
    except httpx.HTTPError as error:
        raise LanguageModelUnavailableError(provider, "transport error") from error


def json_object(provider: str, response: httpx.Response) -> dict[str, Any]:
    """The body of a successful response, which both providers document as a JSON object."""
    if not response.is_success:
        raise error_for_status(provider, response.status_code)
    try:
        body = response.json()
    except ValueError:
        raise LanguageModelInvalidResponseError(provider, "body is not JSON") from None
    if not isinstance(body, dict):
        raise LanguageModelInvalidResponseError(provider, "body is not a JSON object")
    return body
