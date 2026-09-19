"""Single sign-on opts in to rate limiting like every router outside ``/health``.

The routes that present a credential (the callback's state and provider code, the
exchange's one-time code) spend the strict ``auth`` budget, by client IP, like login and
registration: they are where guessing would happen, and the callback makes the API call the
provider. Listing providers and starting a flow present nothing and spend the general budget.
"""

from collections.abc import AsyncIterator
from dataclasses import replace

import httpx
import pytest

from app.bootstrap import build_container, load_settings
from app.infrastructure.rate_limit.in_memory_rate_limiter import InMemoryRateLimiter
from app.main import create_app
from tests.api.conftest import ALL_HEALTHY, RecordingRequestScopes
from tests.rate_limit_fakes import FakeClock

AUTH_LIMIT = 4
ANONYMOUS_LIMIT = 6
RATE_LIMIT_HEADERS = ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset")
TOO_MANY = {"detail": "Too many requests"}


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def client(
    minimal_env: pytest.MonkeyPatch, request_scopes: RecordingRequestScopes, clock: FakeClock
) -> AsyncIterator[httpx.AsyncClient]:
    minimal_env.setenv("RATE_LIMIT__AUTH__LIMIT", str(AUTH_LIMIT))
    minimal_env.setenv("RATE_LIMIT__ANONYMOUS__LIMIT", str(ANONYMOUS_LIMIT))
    container = build_container(load_settings())
    app = create_app(
        container=replace(
            container,
            health_checks=ALL_HEALTHY,
            request_scope=request_scopes,
            identity_providers=request_scopes.sso.providers,
            one_time_store=request_scopes.sso.store,
            rate_limiting=replace(
                container.rate_limiting, limiter=InMemoryRateLimiter(clock=clock)
            ),
        )
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        yield http


async def test_the_exchange_is_limited_like_a_login(client: httpx.AsyncClient) -> None:
    guesses = [
        await client.post("/auth/sso/exchange", json={"code": f"guess-{n}"})
        for n in range(AUTH_LIMIT + 1)
    ]

    assert [response.status_code for response in guesses] == [401] * AUTH_LIMIT + [429]
    assert guesses[-1].json() == TOO_MANY
    assert int(guesses[-1].headers["Retry-After"]) > 0
    assert all(header in guesses[0].headers for header in RATE_LIMIT_HEADERS)


async def test_the_callback_shares_the_strict_budget_with_login_and_exchange(
    client: httpx.AsyncClient,
) -> None:
    await client.post("/auth/login", data={"username": "a@example.com", "password": "x"})
    await client.post("/auth/sso/exchange", json={"code": "guess"})
    for _ in range(AUTH_LIMIT - 2):
        spent = await client.get("/auth/sso/fake/callback", params={"state": "s", "code": "c"})
        assert spent.status_code == 303
        assert spent.headers["X-RateLimit-Limit"] == str(AUTH_LIMIT)

    limited = await client.get("/auth/sso/fake/callback", params={"state": "s", "code": "c"})

    assert limited.status_code == 429
    assert limited.json() == TOO_MANY
    assert "location" not in limited.headers


async def test_a_limited_callback_does_not_spend_the_state(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    """The person waits and retries the same URL: the limiter ran before anything else."""
    started = await client.get("/auth/sso/fake/start")
    callback_url = started.headers["location"].partition("localhost:8000")[2]
    for n in range(AUTH_LIMIT):
        await client.post("/auth/sso/exchange", json={"code": f"guess-{n}"})
    assert (await client.get(callback_url)).status_code == 429

    clock.advance(61)

    retried = await client.get(callback_url)
    assert retried.status_code == 303
    assert "?code=" in retried.headers["location"]


async def test_the_strict_budget_recovers_after_the_window(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    for n in range(AUTH_LIMIT + 1):
        last = await client.post("/auth/sso/exchange", json={"code": f"guess-{n}"})
    assert last.status_code == 429

    clock.advance(61)

    assert (await client.post("/auth/sso/exchange", json={"code": "again"})).status_code == 401


async def test_providers_and_start_spend_the_general_budget_not_the_strict_one(
    client: httpx.AsyncClient,
) -> None:
    responses = [await client.get("/auth/sso/providers") for _ in range(ANONYMOUS_LIMIT - 1)]
    responses.append(await client.get("/auth/sso/fake/start"))

    assert [r.status_code for r in responses] == [200] * (ANONYMOUS_LIMIT - 1) + [303]
    assert responses[0].headers["X-RateLimit-Limit"] == str(ANONYMOUS_LIMIT)
    assert responses[-1].headers["X-RateLimit-Remaining"] == "0"

    limited = await client.get("/auth/sso/fake/start")
    assert limited.status_code == 429
    assert "set-cookie" not in limited.headers
    # ...while the strict budget is untouched
    assert (await client.post("/auth/sso/exchange", json={"code": "x"})).status_code == 401


async def test_the_public_routes_need_no_token_and_ignore_a_bad_one(
    client: httpx.AsyncClient,
) -> None:
    """The general limiter reads an optional bearer; it must never turn these routes into
    authenticated ones."""
    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        assert (await client.get("/auth/sso/providers", headers=headers)).status_code == 200
        assert (await client.get("/auth/sso/fake/start", headers=headers)).status_code == 303
