"""Contract every OneTimeStore adapter must honour (Liskov).

The in-memory fake runs everywhere; the Redis adapter runs the same cases under the
``integration`` marker against the Redis of ``REDIS__URL``. Expiry is proven with a real,
short time to live, because Redis owns its clock.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from app.application.ports.one_time_store import OneTimeStore
from app.infrastructure.cache.one_time_store import RedisOneTimeStore

from app.infrastructure.cache.client import create_redis_client
from app.infrastructure.config.settings import Settings
from tests.sso_fakes import InMemoryOneTimeStore

ADAPTERS = [
    pytest.param("in-memory"),
    pytest.param("redis", marks=pytest.mark.integration),
]
MINUTE = timedelta(minutes=1)


@pytest.fixture(params=ADAPTERS)
async def store(request: pytest.FixtureRequest) -> AsyncIterator[OneTimeStore]:
    if request.param == "in-memory":
        yield InMemoryOneTimeStore()
        return
    redis = create_redis_client(Settings().redis.url)
    yield RedisOneTimeStore(redis)
    await redis.aclose()


def a_key() -> str:
    return f"test:{uuid.uuid4().hex}"


async def test_a_value_is_taken_exactly_once(store: OneTimeStore) -> None:
    key = a_key()
    await store.put(key, "the-value", ttl=MINUTE)

    assert await store.take(key) == "the-value"
    assert await store.take(key) is None


async def test_an_unknown_key_is_none(store: OneTimeStore) -> None:
    assert await store.take(a_key()) is None


async def test_keys_are_independent(store: OneTimeStore) -> None:
    first, second = a_key(), a_key()
    await store.put(first, "one", ttl=MINUTE)
    await store.put(second, "two", ttl=MINUTE)

    assert await store.take(second) == "two"
    assert await store.take(first) == "one"


async def test_a_value_is_gone_once_its_time_to_live_has_passed(store: OneTimeStore) -> None:
    key = a_key()
    await store.put(key, "short-lived", ttl=timedelta(milliseconds=50))

    await asyncio.sleep(0.15)

    assert await store.take(key) is None


async def test_of_many_concurrent_takers_exactly_one_gets_the_value(store: OneTimeStore) -> None:
    """Single use has to hold under a race: two tabs, or a replay beside the real request."""
    key = a_key()
    await store.put(key, "only-once", ttl=MINUTE)

    taken = await asyncio.gather(*(store.take(key) for _ in range(20)))

    assert sorted(value for value in taken if value is not None) == ["only-once"]


async def test_text_round_trips_unchanged(store: OneTimeStore) -> None:
    key = a_key()
    value = '{"provider": "fake", "nonce": "ñ-ü-✓", "binding": "abc"}'
    await store.put(key, value, ttl=MINUTE)

    assert await store.take(key) == value


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1)])
async def test_a_time_to_live_that_is_not_positive_is_refused(
    store: OneTimeStore, ttl: timedelta
) -> None:
    with pytest.raises(ValueError, match="ttl"):
        await store.put(a_key(), "value", ttl=ttl)
