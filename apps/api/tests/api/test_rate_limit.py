"""Rate limiting over HTTP: the three policies, the headers, the 429, the exemptions and
what happens while Redis is away.

The app is the real one, built by the composition root; only the limiter is swapped for the
in-memory adapter on a clock the test moves, so no case sleeps and none needs Redis.
"""

import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from app.infrastructure.rate_limit.in_memory_rate_limiter import InMemoryRateLimiter
from fastapi import FastAPI

from app.bootstrap import build_container, load_settings
from app.domain.user import User
from app.main import create_app
from tests.api.conftest import ALL_HEALTHY, AuthFakes, RecordingRequestScopes
from tests.rate_limit_fakes import FakeClock

AUTH_LIMIT = 3
AUTHENTICATED_LIMIT = 5
ANONYMOUS_LIMIT = 4
WINDOW_SECONDS = 60

ADA_IP = "203.0.113.7"
GRACE_IP = "203.0.113.8"
CREDENTIALS = {"username": "nobody@example.com", "password": "wrong"}
RATE_LIMIT_HEADERS = ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset")

ClientFrom = Callable[[str], httpx.AsyncClient]
AppFactory = Callable[[], FastAPI]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def limited_env(minimal_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Limits low enough to reach in a handful of requests."""
    minimal_env.setenv("RATE_LIMIT__AUTH__LIMIT", str(AUTH_LIMIT))
    minimal_env.setenv("RATE_LIMIT__AUTHENTICATED__LIMIT", str(AUTHENTICATED_LIMIT))
    minimal_env.setenv("RATE_LIMIT__ANONYMOUS__LIMIT", str(ANONYMOUS_LIMIT))
    return minimal_env


@pytest.fixture
def build_app(
    limited_env: pytest.MonkeyPatch, request_scopes: RecordingRequestScopes, clock: FakeClock
) -> AppFactory:
    """Called after the test has finished setting the environment."""

    def _build() -> FastAPI:
        container = build_container(load_settings())
        return create_app(
            container=replace(
                container,
                health_checks=ALL_HEALTHY,
                request_scope=request_scopes,
                rate_limiting=replace(
                    container.rate_limiting, limiter=InMemoryRateLimiter(clock=clock)
                ),
            )
        )

    return _build


@pytest.fixture
async def client_from(build_app: AppFactory) -> AsyncIterator[ClientFrom]:
    """HTTP clients of ONE app, each connecting from the IP address it is given."""
    app = build_app()
    clients: list[httpx.AsyncClient] = []

    def _client(ip: str) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app, client=(ip, 50000))
        clients.append(httpx.AsyncClient(transport=transport, base_url="http://test"))
        return clients[-1]

    async with app.router.lifespan_context(app):
        yield _client
        for client in clients:
            await client.aclose()


@pytest.fixture
def ada(client_from: ClientFrom) -> httpx.AsyncClient:
    return client_from(ADA_IP)


async def _signed_in(auth_fakes: AuthFakes, email: str) -> dict[str, str]:
    """A stored user and their bearer header, without spending any rate limit."""
    user = User(
        id=uuid.uuid4(),
        email=email,
        full_name="Test User",
        hashed_password=auth_fakes.hasher.hash("correct horse"),
        is_active=True,
        created_at=datetime(2026, 1, 5, tzinfo=UTC),
    )
    await auth_fakes.users.add(user)
    return {"Authorization": f"Bearer {auth_fakes.tokens.issue(user.id)}"}


async def _login(client: httpx.AsyncClient, **headers: str) -> httpx.Response:
    return await client.post("/auth/login", data=CREDENTIALS, headers=headers)


# --- the strict policy: POST /auth/login and POST /auth/register, by client IP -------------


async def test_login_is_limited_per_client_ip(ada: httpx.AsyncClient) -> None:
    attempts = [await _login(ada) for _ in range(AUTH_LIMIT)]

    blocked = await _login(ada)

    assert [attempt.status_code for attempt in attempts] == [401] * AUTH_LIMIT
    assert blocked.status_code == 429


async def test_the_429_has_the_standard_error_body_and_says_when_to_retry(
    ada: httpx.AsyncClient, clock: FakeClock
) -> None:
    for _ in range(AUTH_LIMIT):
        await _login(ada)
    clock.advance(18)

    blocked = await _login(ada)

    assert blocked.json() == {"detail": "Too many requests"}
    assert blocked.headers["content-type"] == "application/json"
    assert blocked.headers["retry-after"] == "42"
    assert blocked.headers["x-ratelimit-limit"] == str(AUTH_LIMIT)
    assert blocked.headers["x-ratelimit-remaining"] == "0"
    assert blocked.headers["x-ratelimit-reset"] == "42"


async def test_a_limited_login_never_reaches_the_credentials_check(
    ada: httpx.AsyncClient, request_scopes: RecordingRequestScopes
) -> None:
    for _ in range(AUTH_LIMIT):
        await _login(ada)
    units_of_work = list(request_scopes.events)

    await _login(ada)

    assert request_scopes.events == units_of_work


async def test_login_recovers_after_the_window(ada: httpx.AsyncClient, clock: FakeClock) -> None:
    for _ in range(AUTH_LIMIT + 1):
        await _login(ada)
    clock.advance(WINDOW_SECONDS)

    recovered = await _login(ada)

    assert recovered.status_code == 401
    assert recovered.headers["x-ratelimit-remaining"] == str(AUTH_LIMIT - 1)


async def test_register_and_login_share_the_strict_budget(ada: httpx.AsyncClient) -> None:
    registered = await ada.post(
        "/auth/register",
        json={"email": "ada@example.com", "full_name": "Ada", "password": "correct horse"},
    )
    for _ in range(AUTH_LIMIT - 1):
        await _login(ada)

    assert registered.status_code == 201
    assert registered.headers["x-ratelimit-remaining"] == str(AUTH_LIMIT - 1)
    assert (await _login(ada)).status_code == 429
    assert (await ada.post("/auth/register", json={})).status_code == 429


async def test_another_client_ip_has_its_own_budget(
    ada: httpx.AsyncClient, client_from: ClientFrom
) -> None:
    for _ in range(AUTH_LIMIT + 1):
        await _login(ada)

    assert (await _login(client_from(GRACE_IP))).status_code == 401


# --- the headers ---------------------------------------------------------------------------


async def test_every_response_of_a_limited_route_carries_the_rate_limit_headers(
    ada: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    bearer = await _signed_in(auth_fakes, "ada@example.com")
    responses = {
        "200": await ada.get("/tasks", headers=bearer),
        "401": await _login(ada),
        "404": await ada.get(f"/tasks/{uuid.uuid4()}", headers=bearer),
        "422": await ada.post("/tasks", json={}, headers=bearer),
    }

    assert {name: response.status_code for name, response in responses.items()} == {
        "200": 200,
        "401": 401,
        "404": 404,
        "422": 422,
    }
    for response in responses.values():
        assert all(header in response.headers for header in RATE_LIMIT_HEADERS)
        assert "retry-after" not in response.headers


async def test_the_headers_count_down(ada: httpx.AsyncClient, clock: FakeClock) -> None:
    first = await _login(ada)
    clock.advance(10)
    second = await _login(ada)

    assert (first.headers["x-ratelimit-remaining"], first.headers["x-ratelimit-reset"]) == (
        str(AUTH_LIMIT - 1),
        "60",
    )
    assert (second.headers["x-ratelimit-remaining"], second.headers["x-ratelimit-reset"]) == (
        str(AUTH_LIMIT - 2),
        "50",
    )


async def test_a_browser_may_read_the_rate_limit_headers(ada: httpx.AsyncClient) -> None:
    response = await _login(ada, Origin="http://localhost:3000")

    exposed = response.headers["access-control-expose-headers"].lower()
    assert all(header in exposed for header in (*RATE_LIMIT_HEADERS, "retry-after"))


# --- the general policies: authenticated by user id, anonymous by client IP -----------------


async def test_an_authenticated_caller_is_limited_per_user(
    ada: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    bearer = await _signed_in(auth_fakes, "ada@example.com")
    allowed = [await ada.get("/tasks", headers=bearer) for _ in range(AUTHENTICATED_LIMIT)]

    blocked = await ada.get("/tasks", headers=bearer)

    assert [response.status_code for response in allowed] == [200] * AUTHENTICATED_LIMIT
    assert allowed[0].headers["x-ratelimit-limit"] == str(AUTHENTICATED_LIMIT)
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many requests"}


async def test_the_user_budget_follows_the_user_across_ips_and_routes(
    ada: httpx.AsyncClient, client_from: ClientFrom, auth_fakes: AuthFakes
) -> None:
    bearer = await _signed_in(auth_fakes, "ada@example.com")
    for _ in range(AUTHENTICATED_LIMIT):
        await ada.get("/tasks", headers=bearer)

    elsewhere = await client_from(GRACE_IP).get("/auth/me", headers=bearer)

    assert elsewhere.status_code == 429


async def test_two_users_behind_one_ip_do_not_share_a_budget(
    ada: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    ada_bearer = await _signed_in(auth_fakes, "ada@example.com")
    grace_bearer = await _signed_in(auth_fakes, "grace@example.com")
    for _ in range(AUTHENTICATED_LIMIT + 1):
        await ada.get("/tasks", headers=ada_bearer)

    assert (await ada.get("/tasks", headers=grace_bearer)).status_code == 200


async def test_auth_me_uses_the_general_policy_not_the_strict_one(
    ada: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    bearer = await _signed_in(auth_fakes, "ada@example.com")

    responses = [await ada.get("/auth/me", headers=bearer) for _ in range(AUTH_LIMIT + 1)]

    assert [response.status_code for response in responses] == [200] * (AUTH_LIMIT + 1)
    assert responses[0].headers["x-ratelimit-limit"] == str(AUTHENTICATED_LIMIT)


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer not-a-token"}], ids=["no-token", "bad-token"]
)
async def test_anonymous_traffic_is_limited_per_client_ip(
    ada: httpx.AsyncClient, client_from: ClientFrom, headers: dict[str, str]
) -> None:
    rejected = [await ada.get("/tasks", headers=headers) for _ in range(ANONYMOUS_LIMIT)]

    blocked = await ada.get("/tasks", headers=headers)

    assert [response.status_code for response in rejected] == [401] * ANONYMOUS_LIMIT
    assert rejected[0].headers["x-ratelimit-limit"] == str(ANONYMOUS_LIMIT)
    assert rejected[0].headers["www-authenticate"] == "Bearer"
    assert blocked.status_code == 429
    assert (await client_from(GRACE_IP).get("/tasks", headers=headers)).status_code == 401


async def test_the_three_budgets_are_independent(
    ada: httpx.AsyncClient, auth_fakes: AuthFakes
) -> None:
    bearer = await _signed_in(auth_fakes, "ada@example.com")
    for _ in range(ANONYMOUS_LIMIT + 1):
        await ada.get("/tasks")
    for _ in range(AUTH_LIMIT + 1):
        await _login(ada)

    assert (await ada.get("/tasks", headers=bearer)).status_code == 200


# --- exemptions and the switch ------------------------------------------------------------


@pytest.mark.parametrize("path", ["/health", "/health/ready"])
async def test_health_endpoints_are_never_limited(ada: httpx.AsyncClient, path: str) -> None:
    responses = [await ada.get(path) for _ in range(ANONYMOUS_LIMIT * 5)]

    assert {response.status_code for response in responses} == {200}
    assert not any(header in responses[-1].headers for header in RATE_LIMIT_HEADERS)


async def test_rate_limiting_can_be_switched_off(
    limited_env: pytest.MonkeyPatch, build_app: AppFactory
) -> None:
    limited_env.setenv("RATE_LIMIT__ENABLED", "false")
    transport = httpx.ASGITransport(app=build_app())

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = [await _login(client) for _ in range(AUTH_LIMIT * 3)]

    assert {response.status_code for response in responses} == {401}
    assert not any(header in responses[-1].headers for header in RATE_LIMIT_HEADERS)


# --- which address is "the client" ----------------------------------------------------------


async def test_x_forwarded_for_is_ignored_unless_the_proxy_is_trusted(
    ada: httpx.AsyncClient,
) -> None:
    """Otherwise a fresh header value per request would be a fresh budget per request."""
    responses = [
        await _login(ada, **{"X-Forwarded-For": f"198.51.100.{n}"}) for n in range(AUTH_LIMIT + 1)
    ]

    assert responses[-1].status_code == 429


async def test_behind_a_trusted_proxy_the_forwarded_address_is_the_client(
    limited_env: pytest.MonkeyPatch, build_app: AppFactory
) -> None:
    limited_env.setenv("RATE_LIMIT__TRUST_PROXY", "true")
    transport = httpx.ASGITransport(app=build_app(), client=("10.0.0.1", 50000))  # the proxy

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as proxy:
        for _ in range(AUTH_LIMIT + 1):
            await _login(proxy, **{"X-Forwarded-For": ADA_IP})
        ada_again = await _login(proxy, **{"X-Forwarded-For": ADA_IP})
        grace = await _login(proxy, **{"X-Forwarded-For": GRACE_IP})

    assert ada_again.status_code == 429
    assert grace.status_code == 401


async def test_only_the_entry_the_trusted_proxy_appended_counts(
    limited_env: pytest.MonkeyPatch, build_app: AppFactory
) -> None:
    """Everything left of the last entry was sent by the client and can be forged."""
    limited_env.setenv("RATE_LIMIT__TRUST_PROXY", "true")
    transport = httpx.ASGITransport(app=build_app(), client=("10.0.0.1", 50000))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as proxy:
        responses = [
            await _login(proxy, **{"X-Forwarded-For": f"198.51.100.{n}, {ADA_IP}"})
            for n in range(AUTH_LIMIT + 1)
        ]

    assert responses[-1].status_code == 429


async def test_a_trusted_proxy_that_sends_no_forwarded_header_is_the_client(
    limited_env: pytest.MonkeyPatch, build_app: AppFactory
) -> None:
    limited_env.setenv("RATE_LIMIT__TRUST_PROXY", "true")
    transport = httpx.ASGITransport(app=build_app(), client=("10.0.0.1", 50000))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as proxy:
        responses = [await _login(proxy) for _ in range(AUTH_LIMIT + 1)]

    assert responses[-1].status_code == 429


# --- Redis is away --------------------------------------------------------------------------


async def test_with_redis_unreachable_the_api_keeps_serving_and_warns_once(
    limited_env: pytest.MonkeyPatch,
    request_scopes: RecordingRequestScopes,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The limiter is the real one the composition root wires; REDIS__URL points nowhere."""
    container = replace(build_container(load_settings()), request_scope=request_scopes)
    app = create_app(container=container)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        logins = [await _login(client) for _ in range(AUTH_LIMIT)]
        anonymous = await client.get("/tasks")
        over_the_local_limit = await _login(client)

    assert [response.status_code for response in logins] == [401] * AUTH_LIMIT
    assert all(header in logins[0].headers for header in RATE_LIMIT_HEADERS)
    assert anonymous.status_code == 401
    # Failing open means falling back to this process's own count, not to no limit at all.
    assert over_the_local_limit.status_code == 429
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "rate limit" in warnings[0].getMessage().lower()


# --- OpenAPI --------------------------------------------------------------------------------


async def test_openapi_declares_the_429_on_every_limited_route(ada: httpx.AsyncClient) -> None:
    paths = (await ada.get("/openapi.json")).json()["paths"]

    limited = [
        operation
        for path, operations in paths.items()
        if path.startswith(("/auth", "/tasks"))
        for operation in operations.values()
    ]
    assert len(limited) >= 8  # 3 under /auth, 5 under /tasks
    for operation in limited:
        too_many = operation["responses"]["429"]
        assert too_many["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
        assert set(too_many["headers"]) >= {
            "Retry-After",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        }


async def test_openapi_declares_no_429_on_the_health_routes(ada: httpx.AsyncClient) -> None:
    paths = (await ada.get("/openapi.json")).json()["paths"]

    assert "429" not in paths["/health"]["get"]["responses"]
    assert "429" not in paths["/health/ready"]["get"]["responses"]
