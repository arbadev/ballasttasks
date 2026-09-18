from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import replace

import httpx
import pytest

from app.application.ports.health_check import HealthCheck
from app.bootstrap import build_container, load_settings
from app.main import create_app
from tests.fakes import StubHealthCheck

ClientFactory = Callable[
    [Sequence[HealthCheck] | None], AbstractAsyncContextManager[httpx.AsyncClient]
]

ALL_HEALTHY = (StubHealthCheck("database"), StubHealthCheck("redis"), StubHealthCheck("ai"))


@pytest.fixture
def client_with(minimal_env: pytest.MonkeyPatch) -> ClientFactory:
    """Build an app around a container whose health checks are replaced by fakes.

    ``None`` keeps the real adapters (pointed at services that are down).
    """

    @asynccontextmanager
    async def _client(
        health_checks: Sequence[HealthCheck] | None,
    ) -> AsyncIterator[httpx.AsyncClient]:
        container = build_container(load_settings())
        if health_checks is not None:
            container = replace(container, health_checks=tuple(health_checks))
        app = create_app(container=container)
        transport = httpx.ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        ):
            yield client

    return _client


@pytest.fixture
async def client(client_with: ClientFactory) -> AsyncIterator[httpx.AsyncClient]:
    async with client_with(ALL_HEALTHY) as http_client:
        yield http_client
