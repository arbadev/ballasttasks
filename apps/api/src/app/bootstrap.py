"""Composition root: the ONLY module that imports concrete adapters.

Everything else depends on the ports in ``app.application.ports``. Swapping an adapter
means a new adapter file, one registration line (here or in a registry) and an env
change. No DI framework: the container is a plain frozen dataclass.

``main`` gets ``Settings``, ``load_settings``, ``Container`` and ``build_container`` from
here, so it never imports ``app.infrastructure`` itself.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from celery import Celery
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.application.clock import Clock, utc_now
from app.application.file_changes import FileChanges, files_following_the_transaction
from app.application.ports.activity_feed import ActivityFeed
from app.application.ports.activity_recorder import ActivityRecorder
from app.application.ports.attachment_repository import AttachmentRepository
from app.application.ports.file_storage import FileStorage
from app.application.ports.health_check import HealthCheck
from app.application.ports.identity_provider import IdentityProvider
from app.application.ports.job_queue import JobQueue
from app.application.ports.language_model import LanguageModel
from app.application.ports.one_time_store import OneTimeStore
from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.people_directory import PeopleDirectory
from app.application.ports.project_repository import ProjectRepository
from app.application.ports.rate_limiter import RateLimiter, RateLimitPolicy
from app.application.ports.step_generation_jobs import StepGenerationJobs
from app.application.ports.step_repository import StepRepository
from app.application.ports.task_repository import TaskRepository
from app.application.ports.task_tallies import TaskTallies
from app.application.ports.token_service import TokenService
from app.application.ports.user_directory import UserDirectory
from app.application.ports.user_identity_repository import UserIdentityRepository
from app.application.ports.user_repository import UserRepository
from app.application.sso import SsoConfig
from app.application.step_generation import GenerationOutcome
from app.application.use_cases.add_step import AddStep
from app.application.use_cases.add_steps import AddSteps
from app.application.use_cases.assess_attention import AssessAttention
from app.application.use_cases.attach_file import AttachFile
from app.application.use_cases.attach_link import AttachLink
from app.application.use_cases.authenticate_user import AuthenticateUser
from app.application.use_cases.check_readiness import CheckReadiness
from app.application.use_cases.complete_sso_sign_in import CompleteSsoSignIn
from app.application.use_cases.create_project import CreateProject
from app.application.use_cases.create_task import CreateTask
from app.application.use_cases.delete_step import DeleteStep
from app.application.use_cases.delete_task import DeleteTask
from app.application.use_cases.generate_step_titles import GenerateStepTitles
from app.application.use_cases.get_current_user import GetCurrentUser
from app.application.use_cases.get_project import GetProject
from app.application.use_cases.get_task import GetTask
from app.application.use_cases.list_activity import ListActivity
from app.application.use_cases.list_attachments import ListAttachments
from app.application.use_cases.list_people import ListPeople
from app.application.use_cases.list_projects import ListProjects
from app.application.use_cases.list_steps import ListSteps
from app.application.use_cases.list_tasks import ListTasks
from app.application.use_cases.open_attachment_content import OpenAttachmentContent
from app.application.use_cases.post_comment import PostComment
from app.application.use_cases.redeem_sso_code import RedeemSsoCode
from app.application.use_cases.register_user import RegisterUser
from app.application.use_cases.remove_attachment import RemoveAttachment
from app.application.use_cases.reorder_steps import ReorderSteps
from app.application.use_cases.sign_in_with_identity import SignInWithIdentity
from app.application.use_cases.start_sso_sign_in import StartSsoSignIn
from app.application.use_cases.step_generations import StepGenerations
from app.application.use_cases.summarise_tasks import SummariseTasks
from app.application.use_cases.tally_tasks import TallyTasks
from app.application.use_cases.update_profile import UpdateProfile
from app.application.use_cases.update_project import UpdateProject
from app.application.use_cases.update_step import UpdateStep
from app.application.use_cases.update_task import UpdateTask
from app.infrastructure.ai.health import LanguageModelHealthCheck
from app.infrastructure.ai.http import create_http_client
from app.infrastructure.ai.registry import AI_PROVIDERS, build_language_model
from app.infrastructure.cache.client import create_redis_client
from app.infrastructure.cache.health import RedisHealthCheck
from app.infrastructure.cache.one_time_store import RedisOneTimeStore
from app.infrastructure.config import settings as config
from app.infrastructure.config.settings import ConfigurationError, RateLimitSettings, Settings
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.health import PostgresHealthCheck
from app.infrastructure.db.repositories.activity import SqlAlchemyActivityLog
from app.infrastructure.db.repositories.attachment import SqlAlchemyAttachmentRepository
from app.infrastructure.db.repositories.project import SqlAlchemyProjectRepository
from app.infrastructure.db.repositories.step import SqlAlchemyStepRepository
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.repositories.task_tallies import SqlAlchemyTaskTallies
from app.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from app.infrastructure.db.repositories.user_directory import SqlAlchemyUserDirectory
from app.infrastructure.db.repositories.user_identity import SqlAlchemyUserIdentityRepository
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.db.unit_of_work import transactional_session
from app.infrastructure.identity.registry import IDENTITY_PROVIDERS, build_identity_providers
from app.infrastructure.jobs.factory import create_celery_app
from app.infrastructure.jobs.queue import CeleryJobQueue
from app.infrastructure.jobs.step_generations import CeleryStepGenerationJobs
from app.infrastructure.rate_limit.fail_open_rate_limiter import FailOpenRateLimiter
from app.infrastructure.rate_limit.in_memory_rate_limiter import InMemoryRateLimiter
from app.infrastructure.rate_limit.redis_rate_limiter import RedisRateLimiter
from app.infrastructure.security.argon2_password_hasher import Argon2PasswordHasher
from app.infrastructure.security.jwt_token_service import JwtTokenService
from app.infrastructure.storage.registry import build_file_storage

__all__ = ["Container", "RequestScope", "Settings", "build_container", "load_settings"]

logger = logging.getLogger(__name__)


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
    projects: ProjectRepository
    # The people list: names for the assignee picker, never an email or a hash.
    people: PeopleDirectory
    # The links and files of tasks; the rows go with their task.
    attachments: AttachmentRepository
    file_storage: FileStorage
    file_changes: FileChanges
    max_file_bytes: int
    steps: StepRepository
    # The one way a use case writes to a task's timeline; bound to this scope's session, so
    # an entry commits or rolls back with the change it describes.
    activity: ActivityRecorder
    activity_feed: ActivityFeed
    tallies: TaskTallies
    # Single sign-on: the identities table shares the transaction; the enabled providers
    # and the one-time store are shared by every scope, like the hasher and the tokens.
    identities: UserIdentityRepository
    identity_providers: Mapping[str, IdentityProvider]
    one_time_store: OneTimeStore
    # Every rule that depends on "now" reads this clock; tests pin it.
    clock: Clock = utc_now

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
        return CreateTask(
            self.tasks, self.user_directory, self.projects, self.activity, clock=self.clock
        )

    @property
    def get_task(self) -> GetTask:
        return GetTask(self.tasks)

    @property
    def list_tasks(self) -> ListTasks:
        return ListTasks(self.tasks, clock=self.clock)

    @property
    def update_task(self) -> UpdateTask:
        return UpdateTask(
            self.tasks, self.user_directory, self.projects, self.activity, clock=self.clock
        )

    @property
    def delete_task(self) -> DeleteTask:
        return DeleteTask(self.tasks, self.attachments, self.file_changes)

    @property
    def summarise_tasks(self) -> SummariseTasks:
        return SummariseTasks(self.tasks, self.projects, clock=self.clock)

    @property
    def assess_attention(self) -> AssessAttention:
        return AssessAttention(clock=self.clock)

    @property
    def create_project(self) -> CreateProject:
        return CreateProject(self.projects, clock=self.clock)

    @property
    def get_project(self) -> GetProject:
        return GetProject(self.projects)

    @property
    def list_projects(self) -> ListProjects:
        return ListProjects(self.projects)

    @property
    def update_project(self) -> UpdateProject:
        return UpdateProject(self.projects, clock=self.clock)

    @property
    def list_people(self) -> ListPeople:
        return ListPeople(self.people)

    @property
    def update_profile(self) -> UpdateProfile:
        return UpdateProfile(self.users)

    @property
    def attach_link(self) -> AttachLink:
        return AttachLink(self.tasks, self.attachments, self.activity, clock=self.clock)

    @property
    def list_attachments(self) -> ListAttachments:
        return ListAttachments(self.attachments)

    @property
    def remove_attachment(self) -> RemoveAttachment:
        return RemoveAttachment(
            self.tasks, self.attachments, self.file_changes, self.activity, clock=self.clock
        )

    @property
    def open_attachment_content(self) -> OpenAttachmentContent:
        return OpenAttachmentContent(self.attachments, self.file_storage)

    @property
    def tally_tasks(self) -> TallyTasks:
        return TallyTasks(self.tallies)

    @property
    def list_steps(self) -> ListSteps:
        return ListSteps(self.tasks, self.steps)

    @property
    def add_step(self) -> AddStep:
        return AddStep(self.tasks, self.steps, self.activity, clock=self.clock)

    @property
    def add_steps(self) -> AddSteps:
        return AddSteps(
            self.tasks, self.steps, self.activity, self.user_directory, clock=self.clock
        )

    @property
    def update_step(self) -> UpdateStep:
        return UpdateStep(self.tasks, self.steps, self.activity, clock=self.clock)

    @property
    def reorder_steps(self) -> ReorderSteps:
        return ReorderSteps(self.tasks, self.steps, clock=self.clock)

    @property
    def delete_step(self) -> DeleteStep:
        return DeleteStep(self.tasks, self.steps, clock=self.clock)

    @property
    def post_comment(self) -> PostComment:
        return PostComment(self.tasks, self.activity, self.user_directory, clock=self.clock)

    @property
    def list_activity(self) -> ListActivity:
        return ListActivity(self.tasks, self.activity_feed)


RequestScopeFactory = Callable[[], AbstractAsyncContextManager[RequestScope]]


def _request_scope_factory(
    session_factory: async_sessionmaker[AsyncSession],
    password_hasher: PasswordHasher,
    token_service: TokenService,
    identity_providers: Mapping[str, IdentityProvider],
    one_time_store: OneTimeStore,
    file_storage: FileStorage,
    max_file_bytes: int,
) -> RequestScopeFactory:
    @asynccontextmanager
    async def request_scope() -> AsyncIterator[RequestScope]:
        async with (
            files_following_the_transaction(file_storage) as files,
            transactional_session(session_factory) as session,
        ):
            directory = SqlAlchemyUserDirectory(session)
            activity = SqlAlchemyActivityLog(session)
            yield RequestScope(
                tasks=SqlAlchemyTaskRepository(session),
                users=SqlAlchemyUserRepository(session),
                user_directory=directory,
                projects=SqlAlchemyProjectRepository(session),
                people=directory,
                attachments=SqlAlchemyAttachmentRepository(session),
                file_storage=file_storage,
                file_changes=files,
                max_file_bytes=max_file_bytes,
                steps=SqlAlchemyStepRepository(session),
                activity=activity,
                activity_feed=activity,
                tallies=SqlAlchemyTaskTallies(session),
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
    step_generation_jobs: StepGenerationJobs
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    request_scope: RequestScopeFactory
    redis: Redis
    rate_limiting: RateLimiting
    ai_http_client: AsyncClient
    file_storage: FileStorage
    # Single sign-on. Empty mapping = disabled: the routes answer 404 and list nothing.
    identity_providers: Mapping[str, IdentityProvider]
    one_time_store: OneTimeStore
    sso: SsoConfig

    @property
    def step_generations(self) -> StepGenerations:
        return StepGenerations(self.step_generation_jobs)

    @property
    def start_sso_sign_in(self) -> StartSsoSignIn:
        return StartSsoSignIn(self.identity_providers, self.one_time_store)

    @property
    def attach_file(self) -> AttachFile:
        """The one use case that spans more than one unit of work: it opens a scope to
        check the task, streams the body to the storage with none open, and opens a second
        one to write the row (ADR 0008)."""
        return AttachFile(self.request_scope)

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


async def generate_steps_in_worker(container: Container, task_id: uuid.UUID) -> GenerationOutcome:
    """Release the read transaction before the slow model call; drafts never write rows."""
    async with container.request_scope() as scope:
        task = await scope.tasks.get(task_id)
        if task is None:
            return GenerationOutcome(error="task_deleted")
        existing = tuple(step.title for step in await scope.steps.list_for_task(task_id))
    result = await GenerateStepTitles(
        container.language_model, timeout_seconds=container.settings.ai.timeout_seconds
    ).execute(title=task.title, description=task.description, existing_titles=existing)
    # A deletion during generation also fails. A later deletion is checked on every poll.
    async with container.request_scope() as scope:
        if await scope.tasks.get(task_id) is None:
            return GenerationOutcome(error="task_deleted")
    return result


def _failure_category(error: BaseException) -> str:
    """One word from a fixed set, chosen by exception class alone.

    The cause is never read: its message, arguments and traceback can carry a connection
    string, an API key or a provider response. The class tells an operator which part of
    the deployment is broken without any of that.
    """
    if isinstance(error, ConfigurationError):
        return "configuration"
    if isinstance(error, SQLAlchemyError):
        return "database"
    if isinstance(error, RedisError):
        return "cache"
    return "unexpected"


def _job_correlation_id(task_id: str) -> str:
    """The job's task id, normalised. A message body never reaches a log line raw."""
    try:
        return str(uuid.UUID(task_id))
    except ValueError:
        return "unparsable"


def _run_generation(settings: Settings, task_id: str, celery_app: Celery) -> dict[str, object]:
    async def run() -> GenerationOutcome:
        # The running process already has its Celery application; only the async handles
        # are per job, so a job never replaces ``celery.current_app`` with a second one.
        container = build_container(settings, celery_app=celery_app)
        try:
            return await generate_steps_in_worker(container, uuid.UUID(task_id))
        finally:
            await container.aclose()

    try:
        result = asyncio.run(run())
    except Exception as error:
        # Database/worker failures are as private as provider failures. Celery never
        # receives an exception containing connection strings or response bodies, and
        # neither does this line: a broken deployment is diagnosable from the task id and
        # the category, which is all a swallowed failure is allowed to say.
        logger.warning(
            "Step generation job failed: task=%s category=%s",
            _job_correlation_id(task_id),
            _failure_category(error),
        )
        result = GenerationOutcome(error="worker_failed")
    return {"titles": list(result.titles), "error": result.error}


def build_worker(settings: Settings) -> Celery:
    def generate_steps(task_id: str) -> dict[str, object]:
        return _run_generation(settings, task_id, celery_app)

    celery_app = create_celery_app(
        broker_url=settings.redis.url,
        result_backend=settings.redis.url,
        generate_steps=generate_steps,
    )
    return celery_app


def build_container(settings: Settings, *, celery_app: Celery | None = None) -> Container:
    # First, before any handle is opened: a provider that is enabled without what it needs
    # stops the process here, with a message naming the variable.
    file_storage = build_file_storage(settings.storage)
    identity_providers = build_identity_providers(settings)
    engine = create_engine(settings.database.url, echo=settings.app.debug)
    redis = create_redis_client(settings.redis.url)
    ai_http_client = create_http_client(timeout_seconds=settings.ai.timeout_seconds)
    language_model = build_language_model(settings.ai, ai_http_client)
    session_factory = create_session_factory(engine)
    # A process builds its Celery application once; the worker passes its own in.
    celery_app = celery_app if celery_app is not None else build_worker(settings)
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
        step_generation_jobs=CeleryStepGenerationJobs(celery_app),
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
            file_storage,
            settings.storage.max_bytes,
        ),
        redis=redis,
        rate_limiting=_rate_limiting(settings.rate_limit, redis),
        ai_http_client=ai_http_client,
        file_storage=file_storage,
        identity_providers=identity_providers,
        one_time_store=one_time_store,
        sso=SsoConfig(
            api_public_base_url=settings.sso.api_public_base_url,
            web_callback_url=settings.sso.web_callback_url,
        ),
    )
