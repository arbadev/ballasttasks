import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI

from app.api.security import get_current_user_id
from app.application.ports.health_check import HealthCheck
from app.bootstrap import RequestScope, build_container, load_settings
from app.main import create_app
from tests.fakes import InMemoryTaskRepository, StubHealthCheck

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


USER_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


class RecordingRequestScopes:
    """Stands in for ``Container.request_scope``: same in-memory repository for every
    request, and a record of how each scope ended."""

    def __init__(self, tasks: InMemoryTaskRepository) -> None:
        self.tasks = tasks
        self.events: list[str] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[RequestScope]:
        self.events.append("begin")
        try:
            yield RequestScope(tasks=self.tasks)
        except BaseException:
            self.events.append("rollback")
            raise
        self.events.append("commit")


@pytest.fixture
def tasks() -> InMemoryTaskRepository:
    return InMemoryTaskRepository()


@pytest.fixture
def request_scopes(tasks: InMemoryTaskRepository) -> RecordingRequestScopes:
    return RecordingRequestScopes(tasks)


@pytest.fixture
async def tasks_app(
    minimal_env: pytest.MonkeyPatch, request_scopes: RecordingRequestScopes
) -> AsyncIterator[FastAPI]:
    """The real app around a container of fakes: no database, no Redis."""
    container = replace(
        build_container(load_settings()), health_checks=ALL_HEALTHY, request_scope=request_scopes
    )
    app = create_app(container=container)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def anonymous_client(tasks_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=tasks_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
async def task_client(
    tasks_app: FastAPI, anonymous_client: httpx.AsyncClient
) -> AsyncIterator[httpx.AsyncClient]:
    """Signed in as ``USER_ID`` through the pinned seam, ``get_current_user_id``."""
    tasks_app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    yield anonymous_client
    tasks_app.dependency_overrides.clear()
