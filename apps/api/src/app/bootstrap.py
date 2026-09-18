"""Composition root: the ONLY module that imports concrete adapters.

Everything else depends on the ports in ``app.application.ports``. Swapping an adapter
means a new adapter file, one registration line (here or in a registry) and an env
change. No DI framework: the container is a plain frozen dataclass.

``main`` gets ``Settings``, ``load_settings``, ``Container`` and ``build_container`` from
here, so it never imports ``app.infrastructure`` itself.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.application.ports.health_check import HealthCheck
from app.application.ports.job_queue import JobQueue
from app.application.ports.language_model import LanguageModel
from app.application.use_cases.check_readiness import CheckReadiness
from app.infrastructure.ai.health import LanguageModelHealthCheck
from app.infrastructure.ai.registry import AI_PROVIDERS, build_language_model
from app.infrastructure.cache.client import create_redis_client
from app.infrastructure.cache.health import RedisHealthCheck
from app.infrastructure.config import settings as config
from app.infrastructure.config.settings import Settings
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.health import PostgresHealthCheck
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.jobs.factory import create_celery_app
from app.infrastructure.jobs.queue import CeleryJobQueue

__all__ = ["Container", "Settings", "build_container", "load_settings"]


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    health_checks: Sequence[HealthCheck]
    language_model: LanguageModel
    job_queue: JobQueue
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis

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


def load_settings() -> Settings:
    """Validated settings; the valid AI providers are whatever the registry holds."""
    return config.load_settings(valid_ai_providers=AI_PROVIDERS.keys())


def build_container(settings: Settings) -> Container:
    engine = create_engine(settings.database.url, echo=settings.app.debug)
    redis = create_redis_client(settings.redis.url)
    language_model = build_language_model(settings.ai)
    celery_app = create_celery_app(
        broker_url=settings.redis.url,
        result_backend=settings.redis.url,
    )
    return Container(
        settings=settings,
        # Order is the order reported by GET /health/ready. New check = one line.
        health_checks=(
            PostgresHealthCheck(engine),
            RedisHealthCheck(redis),
            LanguageModelHealthCheck(language_model),
        ),
        language_model=language_model,
        job_queue=CeleryJobQueue(celery_app),
        engine=engine,
        session_factory=create_session_factory(engine),
        redis=redis,
    )
