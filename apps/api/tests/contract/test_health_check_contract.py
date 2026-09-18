"""Contract every HealthCheck adapter must honour (Liskov): bool result, never raises.

Registering a new adapter = one new factory + one line in ``ADAPTERS``.
The default run points the service-backed adapters at a closed port (service DOWN);
the ``integration`` entries run the same suite against the live services.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest

from app.application.ports.health_check import HealthCheck
from app.infrastructure.ai.fake import FakeLanguageModel
from app.infrastructure.ai.health import LanguageModelHealthCheck
from app.infrastructure.cache.client import create_redis_client
from app.infrastructure.cache.health import RedisHealthCheck
from app.infrastructure.config.settings import Settings
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.health import PostgresHealthCheck
from tests.conftest import DOWN_DATABASE_URL, DOWN_REDIS_URL

AdapterFactory = Callable[[], AbstractAsyncContextManager[HealthCheck]]


@asynccontextmanager
async def _postgres(url: str) -> AsyncIterator[HealthCheck]:
    engine = create_engine(url, connect_timeout_seconds=1)
    try:
        yield PostgresHealthCheck(engine)
    finally:
        await engine.dispose()


@asynccontextmanager
async def _redis(url: str) -> AsyncIterator[HealthCheck]:
    client = create_redis_client(url, timeout_seconds=1)
    try:
        yield RedisHealthCheck(client)
    finally:
        await client.aclose()


def postgres_down() -> AbstractAsyncContextManager[HealthCheck]:
    return _postgres(DOWN_DATABASE_URL)


def postgres_live() -> AbstractAsyncContextManager[HealthCheck]:
    return _postgres(Settings().database.url)


def redis_down() -> AbstractAsyncContextManager[HealthCheck]:
    return _redis(DOWN_REDIS_URL)


def redis_live() -> AbstractAsyncContextManager[HealthCheck]:
    return _redis(Settings().redis.url)


@asynccontextmanager
async def ai_fake() -> AsyncIterator[HealthCheck]:
    yield LanguageModelHealthCheck(FakeLanguageModel(model="fake-1"))


ADAPTERS = [
    pytest.param(postgres_down, id="postgres-down"),
    pytest.param(redis_down, id="redis-down"),
    pytest.param(ai_fake, id="ai-fake"),
    pytest.param(postgres_live, id="postgres-live", marks=pytest.mark.integration),
    pytest.param(redis_live, id="redis-live", marks=pytest.mark.integration),
]


@pytest.mark.parametrize("factory", ADAPTERS)
async def test_check_returns_a_bool_and_never_raises(factory: AdapterFactory) -> None:
    async with factory() as health_check:
        assert isinstance(await health_check.check(), bool)


@pytest.mark.parametrize("factory", ADAPTERS)
async def test_name_is_a_non_empty_string(factory: AdapterFactory) -> None:
    async with factory() as health_check:
        assert isinstance(health_check.name, str)
        assert health_check.name


@pytest.mark.parametrize(
    ("factory", "expected"),
    [(postgres_down, False), (redis_down, False), (ai_fake, True)],
    ids=["postgres-down", "redis-down", "ai-fake"],
)
async def test_reports_the_real_state_of_the_dependency(
    factory: AdapterFactory, expected: bool
) -> None:
    async with factory() as health_check:
        assert await health_check.check() is expected


async def test_ai_health_check_never_raises_when_the_model_does() -> None:
    class BrokenModel(FakeLanguageModel):
        async def check(self) -> bool:
            raise ConnectionError("provider unreachable")

    assert await LanguageModelHealthCheck(BrokenModel(model="x")).check() is False
