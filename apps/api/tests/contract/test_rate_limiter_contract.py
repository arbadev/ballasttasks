"""Contract every RateLimiter adapter must honour (Liskov).

The in-memory adapter the API tests rely on, and that stands in for Redis during an
outage, runs here next to the Redis adapter, so a policy behaves the same on both.
Time is a clock the test moves: no case sleeps.
Registering a new adapter = one new entry in ``ADAPTERS`` and one branch in ``limiter``.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from app.application.ports.rate_limiter import RateLimiter, RateLimitPolicy
from app.infrastructure.rate_limit.fail_open_rate_limiter import FailOpenRateLimiter
from app.infrastructure.rate_limit.in_memory_rate_limiter import InMemoryRateLimiter
from app.infrastructure.rate_limit.redis_rate_limiter import RedisRateLimiter

from app.bootstrap import load_settings
from app.infrastructure.cache.client import create_redis_client
from tests.rate_limit_fakes import FakeClock

ADAPTERS = [
    pytest.param("in-memory"),
    pytest.param("fail-open"),
    pytest.param("redis", marks=pytest.mark.integration),
]

THREE_A_MINUTE = RateLimitPolicy(name="three-a-minute", limit=3, window_seconds=60)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(params=ADAPTERS)
async def limiter(request: pytest.FixtureRequest, clock: FakeClock) -> AsyncIterator[RateLimiter]:
    if request.param == "in-memory":
        yield InMemoryRateLimiter(clock=clock)
        return
    if request.param == "fail-open":
        # A healthy primary: the wrapper must be invisible.
        yield FailOpenRateLimiter(InMemoryRateLimiter(clock=clock), InMemoryRateLimiter())
        return

    # Real Redis. A prefix of its own keeps each case apart from the others and from
    # whatever else uses that Redis; the keys expire on their own.
    client = create_redis_client(load_settings().redis.url)
    yield RedisRateLimiter(client, prefix=f"ratelimit-contract-{uuid.uuid4().hex}", clock=clock)
    await client.aclose()


async def test_allows_up_to_the_limit_and_counts_down(limiter: RateLimiter) -> None:
    decisions = [await limiter.hit("ada", THREE_A_MINUTE) for _ in range(3)]

    assert [decision.allowed for decision in decisions] == [True, True, True]
    assert [decision.remaining for decision in decisions] == [2, 1, 0]
    assert {decision.limit for decision in decisions} == {3}


async def test_blocks_the_hit_after_the_limit(limiter: RateLimiter) -> None:
    for _ in range(3):
        await limiter.hit("ada", THREE_A_MINUTE)

    blocked = await limiter.hit("ada", THREE_A_MINUTE)

    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.limit == 3
    assert blocked.reset_after_seconds == 60


async def test_the_window_starts_at_the_first_hit_and_counts_down(
    limiter: RateLimiter, clock: FakeClock
) -> None:
    first = await limiter.hit("ada", THREE_A_MINUTE)
    clock.advance(20)
    second = await limiter.hit("ada", THREE_A_MINUTE)

    assert first.reset_after_seconds == 60
    assert second.reset_after_seconds == 40


async def test_seconds_until_reset_are_rounded_up_so_a_client_never_retries_early(
    limiter: RateLimiter, clock: FakeClock
) -> None:
    await limiter.hit("ada", THREE_A_MINUTE)
    clock.advance(59.5)

    assert (await limiter.hit("ada", THREE_A_MINUTE)).reset_after_seconds == 1


async def test_recovers_after_the_window(limiter: RateLimiter, clock: FakeClock) -> None:
    for _ in range(4):
        await limiter.hit("ada", THREE_A_MINUTE)
    clock.advance(59)
    still_blocked = await limiter.hit("ada", THREE_A_MINUTE)
    clock.advance(1)

    recovered = await limiter.hit("ada", THREE_A_MINUTE)

    assert still_blocked.allowed is False
    assert recovered.allowed is True
    assert recovered.remaining == 2
    assert recovered.reset_after_seconds == 60


async def test_blocked_hits_do_not_extend_the_window(
    limiter: RateLimiter, clock: FakeClock
) -> None:
    for _ in range(3):
        await limiter.hit("ada", THREE_A_MINUTE)
    for _ in range(5):
        clock.advance(10)
        assert (await limiter.hit("ada", THREE_A_MINUTE)).allowed is False
    clock.advance(10)

    assert (await limiter.hit("ada", THREE_A_MINUTE)).allowed is True


async def test_separate_keys_do_not_interfere(limiter: RateLimiter) -> None:
    for _ in range(4):
        await limiter.hit("ada", THREE_A_MINUTE)

    grace = await limiter.hit("grace", THREE_A_MINUTE)

    assert grace.allowed is True
    assert grace.remaining == 2


async def test_the_same_key_under_another_policy_is_counted_separately(
    limiter: RateLimiter,
) -> None:
    ten_an_hour = RateLimitPolicy(name="ten-an-hour", limit=10, window_seconds=3600)
    for _ in range(4):
        await limiter.hit("ada", THREE_A_MINUTE)

    other = await limiter.hit("ada", ten_an_hour)

    assert other.allowed is True
    assert (other.limit, other.remaining, other.reset_after_seconds) == (10, 9, 3600)


async def test_concurrent_hits_never_exceed_the_limit(limiter: RateLimiter) -> None:
    policy = RateLimitPolicy(name="ten-a-minute", limit=10, window_seconds=60)

    decisions = await asyncio.gather(*(limiter.hit("ada", policy) for _ in range(50)))

    assert sum(decision.allowed for decision in decisions) == 10
    assert sorted(d.remaining for d in decisions if d.allowed) == list(range(10))


@pytest.mark.parametrize(("limit", "window_seconds"), [(0, 60), (-1, 60), (3, 0), (3, -5)], ids=str)
def test_a_policy_that_could_never_allow_or_never_reset_is_rejected(
    limit: int, window_seconds: int
) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        RateLimitPolicy(name="broken", limit=limit, window_seconds=window_seconds)
