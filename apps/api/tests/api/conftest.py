import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field, replace

import httpx
import pytest
from fastapi import FastAPI

from app.api.security import get_current_user_id
from app.application.clock import Clock, utc_now
from app.application.ports.health_check import HealthCheck
from app.application.ports.identity_provider import IdentityProvider
from app.bootstrap import RequestScope, build_container, load_settings
from app.infrastructure.identity.fake import FakeIdentityProvider
from app.main import create_app
from tests.activity_fakes import InMemoryActivityLog, InMemoryStepRepository, InMemoryTaskTallies
from tests.auth_fakes import (
    FakePasswordHasher,
    FakeTokenService,
    InMemoryUserDirectory,
    InMemoryUserRepository,
)
from tests.fakes import InMemoryProjectRepository, InMemoryTaskRepository, StubHealthCheck
from tests.sso_fakes import InMemoryOneTimeStore, InMemoryUserIdentityRepository, MutableClock

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


@dataclass(frozen=True, slots=True)
class AuthFakes:
    users: InMemoryUserRepository
    hasher: FakePasswordHasher
    tokens: FakeTokenService


@dataclass(frozen=True, slots=True)
class SsoFakes:
    """Single sign-on with only the fake provider enabled; a test adds or removes providers
    in ``providers`` and moves ``clock`` to let states and exchange codes expire."""

    clock: MutableClock
    store: InMemoryOneTimeStore
    identities: InMemoryUserIdentityRepository
    providers: dict[str, IdentityProvider] = field(
        default_factory=lambda: {"fake": FakeIdentityProvider()}
    )


class RecordingRequestScopes:
    """Stands in for ``Container.request_scope``: the same in-memory repositories for
    every request, and a record of how each scope ended."""

    def __init__(self, tasks: InMemoryTaskRepository, auth: AuthFakes, sso: SsoFakes) -> None:
        self.tasks = tasks
        self.auth = auth
        self.steps = InMemoryStepRepository(tasks)
        self.activity = InMemoryActivityLog(tasks)
        self.sso = sso
        self.events: list[str] = []
        # The real clock unless a test pins it: ``request_scopes.clock = lambda: NOW``.
        self.clock: Clock = utc_now

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[RequestScope]:
        self.events.append("begin")
        try:
            yield RequestScope(
                tasks=self.tasks,
                users=self.auth.users,
                user_directory=InMemoryUserDirectory(self.auth.users),
                projects=self.tasks.projects,
                people=InMemoryUserDirectory(self.auth.users),
                steps=self.steps,
                activity=self.activity,
                activity_feed=self.activity,
                tallies=InMemoryTaskTallies(self.steps, self.activity),
                clock=lambda: self.clock(),
                password_hasher=self.auth.hasher,
                token_service=self.auth.tokens,
                identities=self.sso.identities,
                identity_providers=self.sso.providers,
                one_time_store=self.sso.store,
            )
        except BaseException:
            self.events.append("rollback")
            raise
        self.events.append("commit")


@pytest.fixture
def auth_fakes() -> AuthFakes:
    return AuthFakes(InMemoryUserRepository(), FakePasswordHasher(), FakeTokenService())


@pytest.fixture
def tasks(auth_fakes: AuthFakes) -> InMemoryTaskRepository:
    return InMemoryTaskRepository(auth_fakes.users, InMemoryProjectRepository())


@pytest.fixture
def sso_fakes() -> SsoFakes:
    clock = MutableClock()
    return SsoFakes(clock, InMemoryOneTimeStore(clock), InMemoryUserIdentityRepository())


@pytest.fixture
def request_scopes(
    tasks: InMemoryTaskRepository, auth_fakes: AuthFakes, sso_fakes: SsoFakes
) -> RecordingRequestScopes:
    return RecordingRequestScopes(tasks, auth_fakes, sso_fakes)


@pytest.fixture
async def tasks_app(
    minimal_env: pytest.MonkeyPatch, request_scopes: RecordingRequestScopes
) -> AsyncIterator[FastAPI]:
    """The real app around a container of fakes: no database, no Redis."""
    container = replace(
        build_container(load_settings()),
        health_checks=ALL_HEALTHY,
        request_scope=request_scopes,
        identity_providers=request_scopes.sso.providers,
        one_time_store=request_scopes.sso.store,
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


@pytest.fixture
def auth_app(tasks_app: FastAPI) -> FastAPI:
    """The same app of fakes, named for the auth tests: users, hasher and tokens are the
    ``auth_fakes``; nobody is signed in through an override."""
    return tasks_app


@pytest.fixture
def auth_client(anonymous_client: httpx.AsyncClient) -> httpx.AsyncClient:
    return anonymous_client
