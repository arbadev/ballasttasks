"""Composition root: the ONLY module that imports concrete adapters.

Everything else depends on the ports in ``app.application.ports``. Swapping an adapter
means a new adapter file, one registration line (here or in a registry) and an env
change. No DI framework: the container is a plain frozen dataclass.

``main`` gets ``Settings``, ``load_settings``, ``Container`` and ``build_container`` from
here, so it never imports ``app.infrastructure`` itself.
"""

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.application.ports.health_check import HealthCheck
from app.application.ports.identity_provider import IdentityProvider
from app.application.ports.job_queue import JobQueue
from app.application.ports.language_model import LanguageModel
from app.application.ports.one_time_store import OneTimeStore
from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.rate_limiter import RateLimiter, RateLimitPolicy
from app.application.ports.task_repository import TaskRepository
from app.application.ports.token_service import TokenService
from app.application.ports.user_directory import UserDirectory
from app.application.ports.user_identity_repository import UserIdentityRepository
from app.application.ports.user_repository import UserRepository
from app.application.sso import SsoConfig
from app.application.use_cases.authenticate_user import AuthenticateUser
from app.application.use_cases.check_readiness import CheckReadiness
from app.application.use_cases.complete_sso_sign_in import CompleteSsoSignIn
from app.application.use_cases.create_task import CreateTask
from app.application.use_cases.delete_task import DeleteTask
from app.application.use_cases.get_current_user import GetCurrentUser
from app.application.use_cases.get_task import GetTask
from app.application.use_cases.list_tasks import ListTasks
from app.application.use_cases.redeem_sso_code import RedeemSsoCode
from app.application.use_cases.register_user import RegisterUser
from app.application.use_cases.sign_in_with_identity import SignInWithIdentity
from app.application.use_cases.start_sso_sign_in import StartSsoSignIn
from app.application.use_cases.update_task import UpdateTask
from app.infrastructure.ai.health import LanguageModelHealthCheck
from app.infrastructure.ai.http import create_http_client
from app.infrastructure.ai.registry import AI_PROVIDERS, build_language_model
from app.infrastructure.cache.client import create_redis_client
from app.infrastructure.cache.health import RedisHealthCheck
from app.infrastructure.cache.one_time_store import RedisOneTimeStore
from app.infrastructure.config import settings as config
from app.infrastructure.config.settings import RateLimitSettings, Settings
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.health import PostgresHealthCheck
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from app.infrastructure.db.repositories.user_directory import SqlAlchemyUserDirectory
from app.infrastructure.db.repositories.user_identity import SqlAlchemyUserIdentityRepository
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.db.unit_of_work import transactional_session
from app.infrastructure.identity.registry import IDENTITY_PROVIDERS, build_identity_providers
from app.infrastructure.jobs.factory import create_celery_app
from app.infrastructure.jobs.queue import CeleryJobQueue
from app.infrastructure.rate_limit.fail_open_rate_limiter import FailOpenRateLimiter
from app.infrastructure.rate_limit.in_memory_rate_limiter import InMemoryRateLimiter
from app.infrastructure.rate_limit.redis_rate_limiter import RedisRateLimiter
from app.infrastructure.security.argon2_password_hasher import Argon2PasswordHasher
from app.infrastructure.security.jwt_token_service import JwtTokenService

__all__ = ["Container", "RequestScope", "Settings", "build_container", "load_settings"]


@dataclass(frozen=True, slots=True)
class RequestScope:
    """One unit of work: repositories bound to ONE session, and the use cases on top.

    Everything done through a scope commits or rolls back together (see
    ``app.infrastructure.db.unit_of_work``). New repository = one field here and one
    argument in ``_request_scope_factory``.
    """

    tasks: TaskRepository
    users: UserRepository
    # All the task use cases may know about users: "can this id be given a task?".
    user_directory: UserDirectory
    # Stateless and shared by every scope; they travel with it because the auth use cases
    # need them next to the users repository.
    password_hasher: PasswordHasher
    token_service: TokenService
    # Single sign-on: the identities table shares the transaction; the enabled providers
    # and the one-time store are shared by every scope, like the hasher and the tokens.
    identities: UserIdentityRepository
    identity_providers: Mapping[str, IdentityProvider]
    one_time_store: OneTimeStore

    @property
    def register_user(self) -> RegisterUser:
        return RegisterUser(self.users, self.password_hasher)

    @property
    def authenticate_user(self) -> AuthenticateUser:
        return AuthenticateUser(self.users, self.password_hasher, self.token_service)

    @property
    def get_current_user(self) -> GetCurrentUser:
        return GetCurrentUser(self.users, self.token_service)

    @property
    def complete_sso_sign_in(self) -> CompleteSsoSignIn:
        return CompleteSsoSignIn(
            self.identity_providers,
            self.one_time_store,
            SignInWithIdentity(self.users, self.identities),
        )

    @property
    def redeem_sso_code(self) -> RedeemSsoCode:
        return RedeemSsoCode(self.one_time_store, self.users, self.token_service)

    @property
    def create_task(self) -> CreateTask:
        return CreateTask(self.tasks, self.user_directory)

    @property
    def get_task(self) -> GetTask:
        return GetTask(self.tasks)

    @property
    def list_tasks(self) -> ListTasks:
        return ListTasks(self.tasks)

    @property
    def update_task(self) -> UpdateTask:
        return UpdateTask(self.tasks, self.user_directory)

    @property
    def delete_task(self) -> DeleteTask:
        return DeleteTask(self.tasks)


RequestScopeFactory = Callable[[], AbstractAsyncContextManager[RequestScope]]


def _request_scope_factory(
    session_factory: async_sessionmaker[AsyncSession],
    password_hasher: PasswordHasher,
    token_service: TokenService,
    identity_providers: Mapping[str, IdentityProvider],
    one_time_store: OneTimeStore,
) -> RequestScopeFactory:
    @asynccontextmanager
    async def request_scope() -> AsyncIterator[RequestScope]:
        async with transactional_session(session_factory) as session:
            yield RequestScope(
                tasks=SqlAlchemyTaskRepository(session),
                users=SqlAlchemyUserRepository(session),
                user_directory=SqlAlchemyUserDirectory(session),
                password_hasher=password_hasher,
                token_service=token_service,
                identities=SqlAlchemyUserIdentityRepository(session),
                identity_providers=identity_providers,
                one_time_store=one_time_store,
            )

    return request_scope


@dataclass(frozen=True, slots=True)
class RateLimiting:
    """What the HTTP layer needs to limit requests: the limiter and the rules from settings."""

    limiter: RateLimiter
    enabled: bool
    trust_proxy: bool
    auth: RateLimitPolicy
    authenticated: RateLimitPolicy
    anonymous: RateLimitPolicy


def _rate_limiting(settings: RateLimitSettings, redis: Redis) -> RateLimiting:
    return RateLimiting(
        # Redis decides; while it is unreachable each process counts on its own (fail open).
        limiter=FailOpenRateLimiter(
            RedisRateLimiter(redis, prefix=settings.key_prefix), InMemoryRateLimiter()
        ),
        enabled=settings.enabled,
        trust_proxy=settings.trust_proxy,
        auth=RateLimitPolicy("auth", settings.auth.limit, settings.auth.window_seconds),
        authenticated=RateLimitPolicy(
            "authenticated", settings.authenticated.limit, settings.authenticated.window_seconds
        ),
        anonymous=RateLimitPolicy(
            "anonymous", settings.anonymous.limit, settings.anonymous.window_seconds
        ),
    )


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    health_checks: Sequence[HealthCheck]
    language_model: LanguageModel
    job_queue: JobQueue
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    request_scope: RequestScopeFactory
    redis: Redis
    rate_limiting: RateLimiting
    ai_http_client: AsyncClient
    # Single sign-on. Empty mapping = disabled: the routes answer 404 and list nothing.
    identity_providers: Mapping[str, IdentityProvider]
    one_time_store: OneTimeStore
    sso: SsoConfig

    @property
    def start_sso_sign_in(self) -> StartSsoSignIn:
        return StartSsoSignIn(self.identity_providers, self.one_time_store)

    @property
    def check_readiness(self) -> CheckReadiness:
        return CheckReadiness(
            self.health_checks,
            timeout_seconds=self.settings.app.health_check_timeout_seconds,
        )

    async def aclose(self) -> None:
        """Release the handles this container owns."""
        await self.engine.dispose()
        await self.redis.aclose()
        await self.ai_http_client.aclose()


def load_settings() -> Settings:
    """Validated settings; the valid AI and identity providers are whatever the registries
    hold."""
    return config.load_settings(
        valid_ai_providers=AI_PROVIDERS.keys(), valid_sso_providers=IDENTITY_PROVIDERS.keys()
    )


def build_container(settings: Settings) -> Container:
    # First, before any handle is opened: a provider that is enabled without what it needs
    # stops the process here, with a message naming the variable.
    identity_providers = build_identity_providers(settings)
    engine = create_engine(settings.database.url, echo=settings.app.debug)
    redis = create_redis_client(settings.redis.url)
    ai_http_client = create_http_client(timeout_seconds=settings.ai.timeout_seconds)
    language_model = build_language_model(settings.ai, ai_http_client)
    session_factory = create_session_factory(engine)
    celery_app = create_celery_app(
        broker_url=settings.redis.url,
        result_backend=settings.redis.url,
    )
    one_time_store = RedisOneTimeStore(redis)
    return Container(
        settings=settings,
        # Order is the order reported by GET /health/ready. New check = one line.
        health_checks=(
            PostgresHealthCheck(engine),
            RedisHealthCheck(redis),
            LanguageModelHealthCheck(language_model, cache_seconds=settings.ai.check_cache_seconds),
        ),
        language_model=language_model,
        job_queue=CeleryJobQueue(celery_app),
        engine=engine,
        session_factory=session_factory,
        request_scope=_request_scope_factory(
            session_factory,
            Argon2PasswordHasher(),
            JwtTokenService(
                settings.auth.jwt_secret.get_secret_value(),
                algorithm=settings.auth.jwt_algorithm,
                expires_in=timedelta(minutes=settings.auth.access_token_expire_minutes),
            ),
            identity_providers,
            one_time_store,
        ),
        redis=redis,
        rate_limiting=_rate_limiting(settings.rate_limit, redis),
        ai_http_client=ai_http_client,
        identity_providers=identity_providers,
        one_time_store=one_time_store,
        sso=SsoConfig(
            api_public_base_url=settings.sso.api_public_base_url,
            web_callback_url=settings.sso.web_callback_url,
        ),
    )
