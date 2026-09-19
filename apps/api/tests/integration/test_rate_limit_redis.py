"""The Redis rate limiter against real Redis: what the shared contract suite cannot see
(the keys themselves, Redis's own clock) and the whole API under a concurrent burst."""

import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from redis.asyncio import Redis

from app.application.ports.rate_limiter import RateLimitPolicy
from app.bootstrap import build_container, load_settings
from app.infrastructure.cache.client import create_redis_client
from app.infrastructure.rate_limit.redis_rate_limiter import RedisRateLimiter
from app.main import create_app

pytestmark = pytest.mark.integration

FIVE_A_MINUTE = RateLimitPolicy(name="five-a-minute", limit=5, window_seconds=60)
AUTH_LIMIT = 5
CREDENTIALS = {"username": "nobody@example.com", "password": "wrong"}


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = create_redis_client(load_settings().redis.url)
    yield client
    await client.aclose()


@pytest.fixture
def prefix() -> str:
    return f"ratelimit-test-{uuid.uuid4().hex}"


async def test_a_key_expires_on_its_own_when_its_window_ends(redis: Redis, prefix: str) -> None:
    limiter = RedisRateLimiter(redis, prefix=prefix)

    for _ in range(7):  # blocked hits included: none of them may push the expiry back
        await limiter.hit("ip:203.0.113.7", FIVE_A_MINUTE)

    keys = [key async for key in redis.scan_iter(match=f"{prefix}:*")]
    assert keys == [f"{prefix}:five-a-minute:ip:203.0.113.7"]
    assert 0 < await redis.pttl(keys[0]) <= 60_000


async def test_without_an_injected_clock_redis_time_runs_the_window(
    redis: Redis, prefix: str
) -> None:
    one_a_second = RateLimitPolicy(name="one-a-second", limit=1, window_seconds=1)
    limiter = RedisRateLimiter(redis, prefix=prefix)

    first = await limiter.hit("ada", one_a_second)
    blocked = await limiter.hit("ada", one_a_second)
    await asyncio.sleep(1.1)
    recovered = await limiter.hit("ada", one_a_second)

    assert (first.allowed, blocked.allowed, recovered.allowed) == (True, False, True)
    assert blocked.reset_after_seconds == 1
    # The expired key is gone, not merely ignored.
    await asyncio.sleep(1.1)
    assert [key async for key in redis.scan_iter(match=f"{prefix}:*")] == []


async def test_a_burst_from_many_connections_never_exceeds_the_limit(prefix: str) -> None:
    """Separate clients, so the hits really race inside Redis instead of queueing on one socket."""
    url = load_settings().redis.url
    clients = [create_redis_client(url) for _ in range(10)]
    limiters = [RedisRateLimiter(client, prefix=prefix) for client in clients]

    decisions = await asyncio.gather(
        *(limiter.hit("ada", FIVE_A_MINUTE) for limiter in limiters for _ in range(10))
    )
    for client in clients:
        await client.aclose()

    assert len(decisions) == 100
    assert sum(decision.allowed for decision in decisions) == 5


async def test_a_concurrent_burst_of_logins_lets_exactly_the_limit_through(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real app, PostgreSQL and Redis: 40 logins at once from one address."""
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("RATE_LIMIT__AUTH__LIMIT", str(AUTH_LIMIT))
    app = create_app(container=build_container(load_settings()))

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        responses = await asyncio.gather(
            *(http.post("/auth/login", data=CREDENTIALS) for _ in range(40))
        )
        health = await http.get("/health")

    statuses = [response.status_code for response in responses]
    assert statuses.count(401) == AUTH_LIMIT
    assert statuses.count(429) == 40 - AUTH_LIMIT
    blocked = next(response for response in responses if response.status_code == 429)
    assert blocked.json() == {"detail": "Too many requests"}
    assert 0 < int(blocked.headers["retry-after"]) <= 60
    assert blocked.headers["x-ratelimit-limit"] == str(AUTH_LIMIT)
    assert blocked.headers["x-ratelimit-remaining"] == "0"
    assert health.status_code == 200
