from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, replace

import httpx
import pytest
from fastapi import FastAPI

from app.application.ports.health_check import HealthCheck
from app.bootstrap import build_container, load_settings
from app.main import create_app
from tests.auth_fakes import FakePasswordHasher, FakeTokenService, InMemoryUserRepository
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


@dataclass(frozen=True, slots=True)
class AuthFakes:
    users: InMemoryUserRepository
    hasher: FakePasswordHasher
    tokens: FakeTokenService


@pytest.fixture
def auth_fakes() -> AuthFakes:
    return AuthFakes(InMemoryUserRepository(), FakePasswordHasher(), FakeTokenService())


@pytest.fixture
async def auth_app(minimal_env: pytest.MonkeyPatch, auth_fakes: AuthFakes) -> FastAPI:
    """The real app around a container whose user and auth adapters are fakes: no database."""
    container = replace(
        build_container(load_settings()),
        health_checks=ALL_HEALTHY,
        user_repository=auth_fakes.users,
        password_hasher=auth_fakes.hasher,
        token_service=auth_fakes.tokens,
    )
    return create_app(container=container)


@pytest.fixture
async def auth_client(auth_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=auth_app)
    async with (
        auth_app.router.lifespan_context(auth_app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as http_client,
    ):
        yield http_client
