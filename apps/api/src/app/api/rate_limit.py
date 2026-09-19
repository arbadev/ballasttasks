"""Rate limiting over HTTP: which budget a request spends, the 429, and the headers.

A router (or route) opts in with one of two dependencies; a route without one, like the
health endpoints, is not limited:

- ``limit_auth_attempts``: the strict ``auth`` policy, keyed by client IP. For the routes
  that take credentials, where the caller is by definition not identified yet.
- ``limit_requests``: the ``authenticated`` policy keyed by user id when the bearer token
  resolves to a user, otherwise the ``anonymous`` policy keyed by client IP (the route then
  answers its 401). A user keeps one budget across addresses, and users who share an
  address (an office, a carrier NAT) do not spend each other's.

Both are the same few lines, ``_enforce``; they differ only in how they name the caller.
The decision is left on ``request.state`` and ``RateLimitHeadersMiddleware`` copies it onto
whatever response follows, so a 401, 404 or 422 carries the headers too, not only a 2xx.

Headers: ``X-RateLimit-Limit``, ``X-RateLimit-Remaining`` and ``X-RateLimit-Reset``, the
last in SECONDS FROM NOW (as ``Retry-After``, which a 429 adds with the same value), not a
timestamp: a client needs no synchronised clock to use it.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException, Request, status
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.dependencies import RateLimiting, RateLimitingDep
from app.api.schemas.errors import ErrorResponse
from app.api.security import OptionalStreamingUserId, OptionalUserId
from app.application.ports.rate_limiter import RateLimitDecision, RateLimitPolicy

_STATE_KEY = "rate_limit_decision"
RATE_LIMIT_HEADERS = (
    "Retry-After",
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
)


def _seconds(description: str) -> dict[str, Any]:
    return {"description": description, "schema": {"type": "integer", "minimum": 0}}


# For ``responses=`` of every router or route that uses one of the dependencies below.
TOO_MANY_REQUESTS: Mapping[int | str, dict[str, Any]] = {
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponse,
        "description": "Rate limit exceeded; retry after `Retry-After` seconds",
        "headers": {
            "Retry-After": _seconds("Seconds until the request may be retried"),
            "X-RateLimit-Limit": _seconds("Requests allowed per window"),
            "X-RateLimit-Remaining": _seconds("Requests left in the current window"),
            "X-RateLimit-Reset": _seconds("Seconds until the current window ends"),
        },
    }
}


def client_ip(request: Request, *, trust_proxy: bool) -> str:
    """The address a per-IP budget is charged to.

    By default it is the peer of the TCP connection, the one address a client cannot
    choose. ``X-Forwarded-For`` is just a request header: honouring it from anyone would
    let a client claim a new address, and so a fresh budget, with every request (or spend
    someone else's). It is read only when ``RATE_LIMIT__TRUST_PROXY`` says the API sits
    behind a reverse proxy that sets it, where the peer is always the proxy and would
    otherwise put every client in one bucket.

    Even then only the LAST entry counts: that is the one the trusted proxy appended, the
    address that connected to it. Everything to its left arrived from the client and can
    be forged. (One proxy hop is assumed; see ADR 0004.) A proxy may append its entry as a
    header line of its own instead of extending the client's, so every line is read, in
    order: the last entry of the last line is still the proxy's.
    """
    if trust_proxy:
        lines = request.headers.getlist("x-forwarded-for")
        forwarded = ",".join(lines).rpartition(",")[2].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


async def _enforce(
    request: Request, rate_limiting: RateLimiting, policy: RateLimitPolicy, key: str
) -> None:
    if not rate_limiting.enabled:
        return
    decision = await rate_limiting.limiter.hit(key, policy)
    setattr(request.state, _STATE_KEY, decision)
    if not decision.allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests")


async def limit_auth_attempts(request: Request, rate_limiting: RateLimitingDep) -> None:
    """Brute-force protection.

    Runs before the body is validated, a unit of work is opened or a password is hashed.
    (Not before the body is received: FastAPI reads it before it solves dependencies.)
    """
    ip = client_ip(request, trust_proxy=rate_limiting.trust_proxy)
    await _enforce(request, rate_limiting, rate_limiting.auth, f"ip:{ip}")


async def _limit_caller(
    request: Request, rate_limiting: RateLimiting, user_id: uuid.UUID | None
) -> None:
    if user_id is not None:
        await _enforce(request, rate_limiting, rate_limiting.authenticated, f"user:{user_id}")
        return
    ip = client_ip(request, trust_proxy=rate_limiting.trust_proxy)
    await _enforce(request, rate_limiting, rate_limiting.anonymous, f"ip:{ip}")


async def limit_requests(
    request: Request, rate_limiting: RateLimitingDep, user_id: OptionalUserId
) -> None:
    await _limit_caller(request, rate_limiting, user_id)


async def limit_streaming_requests(
    request: Request, rate_limiting: RateLimitingDep, user_id: OptionalStreamingUserId
) -> None:
    """``limit_requests`` for a route that streams its body: the same two policies, with
    the caller named apart from the request's unit of work (``api/security.py``)."""
    await _limit_caller(request, rate_limiting, user_id)


def _headers(decision: RateLimitDecision) -> dict[str, str]:
    headers = {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Reset": str(decision.reset_after_seconds),
    }
    if not decision.allowed:
        headers["Retry-After"] = str(decision.reset_after_seconds)
    return headers


class RateLimitHeadersMiddleware:
    """Adds the rate limit headers to the response of every request that was counted.

    A dependency can only set headers on the response of a route that returns normally;
    an error response is built elsewhere. This sees them all. Pure ASGI: it touches the
    response start message and nothing else (no body buffering).
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            decision = scope.get("state", {}).get(_STATE_KEY)
            if message["type"] == "http.response.start" and decision is not None:
                MutableHeaders(scope=message).update(_headers(decision))
            await send(message)

        await self._app(scope, receive, send_with_headers)
