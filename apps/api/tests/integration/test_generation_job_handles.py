"""A real generation job against real PostgreSQL: its handles are its own, and it closes them.

Success and failure take the same path out of ``asyncio.run``, so neither may leave an
engine, a Redis client or the provider's HTTP client open, and no job may reuse another's.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.bootstrap import build_worker, load_settings
from app.infrastructure.ai.fake import FakeLanguageModel
from app.infrastructure.ai.registry import AI_PROVIDERS
from app.infrastructure.config.settings import AiSettings
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.db.unit_of_work import transactional_session
from app.infrastructure.jobs.step_generations import JOB_NAME
from tests import builders
from tests.postgres import INSERT_USER, user_row

pytestmark = pytest.mark.integration

DRAFTS = ["Clarify the goal", "Implement the task", "Verify the result"]


async def test_sequential_jobs_generate_and_close_handles_of_their_own(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("AI__PROVIDER", "recording")
    clients: list[AsyncClient] = []

    def recording(ai: AiSettings, client: AsyncClient) -> FakeLanguageModel:
        clients.append(client)
        return FakeLanguageModel(model=ai.model)

    monkeypatch.setitem(AI_PROVIDERS, "recording", recording)

    creator = user_row()
    # The shared test database keeps what other modules committed: a key of its own.
    task = builders.a_task(
        creator["id"], key=f"GH-{uuid.uuid4().int % 900_000_000 + 1}", now=datetime.now(UTC)
    )
    engine = create_engine(migrated_database_url)
    session_factory = create_session_factory(engine)
    try:
        async with transactional_session(session_factory) as session:
            await session.execute(INSERT_USER, creator)
            await SqlAlchemyTaskRepository(session).add(task)

        celery_app = build_worker(load_settings())
        job = celery_app.tasks[JOB_NAME]
        try:
            # Each job blocks on its own asyncio.run, so it runs off this test's loop.
            drafted = await asyncio.to_thread(job, task_id=str(task.id))
            missing = await asyncio.to_thread(job, task_id=str(uuid.uuid4()))
        finally:
            celery_app.close()

        assert drafted == {"titles": DRAFTS, "error": None}
        assert missing == {"titles": [], "error": "task_deleted"}
        # Drafting stays a proposal: the job wrote no steps.
        async with transactional_session(session_factory) as session:
            assert await SqlAlchemyTaskRepository(session).get(task.id) == task

        assert len(clients) == 2
        assert clients[0] is not clients[1]
        assert [client.is_closed for client in clients] == [True, True]
    finally:
        async with transactional_session(session_factory) as session:
            await SqlAlchemyTaskRepository(session).delete(task.id)
        await engine.dispose()
