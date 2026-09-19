"""Step positions under concurrency, against real PostgreSQL: dense and unique, always.

Every step use case loads its task with ``get_for_update`` first, so the writers of one
task's steps take turns; each of them then numbers a list nobody else is changing.
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.use_cases.add_step import AddStep
from app.application.use_cases.add_steps import MAX_STEPS_AT_ONCE, AddSteps
from app.application.use_cases.delete_step import DeleteStep
from app.application.use_cases.reorder_steps import ReorderSteps
from app.domain.step import MAX_STEPS_PER_TASK, InvalidStepError, InvalidStepOrderError, Step
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.activity import SqlAlchemyActivityLog
from app.infrastructure.db.repositories.step import SqlAlchemyStepRepository
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.repositories.user_directory import SqlAlchemyUserDirectory
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.db.unit_of_work import transactional_session
from tests.builders import a_task
from tests.postgres import INSERT_USER, run_alembic, temporary_database, user_row

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]
WRITERS = 12


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with temporary_database() as url:
        run_alembic(url, "upgrade", "head")
        yield url


@pytest.fixture
async def session_factory(database_url: str) -> AsyncIterator[SessionFactory]:
    engine = create_engine(database_url)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def actor(session_factory: SessionFactory) -> uuid.UUID:
    user = user_row()
    async with transactional_session(session_factory) as session:
        await session.execute(INSERT_USER, user)
    return user["id"]


@pytest.fixture
async def task_id(session_factory: SessionFactory, actor: uuid.UUID) -> uuid.UUID:
    task = a_task(actor, key=f"CS-{uuid.uuid4().int % 10**8}")
    async with transactional_session(session_factory) as session:
        await SqlAlchemyTaskRepository(session).add(task)
    return task.id


async def steps_of(session_factory: SessionFactory, task_id: uuid.UUID) -> list[Step]:
    async with transactional_session(session_factory) as session:
        return list(await SqlAlchemyStepRepository(session).list_for_task(task_id))


async def add_step(
    session_factory: SessionFactory, task_id: uuid.UUID, actor: uuid.UUID, title: str
) -> Step:
    """One request: its own session, its own transaction."""
    async with transactional_session(session_factory) as session:
        return await AddStep(
            SqlAlchemyTaskRepository(session),
            SqlAlchemyStepRepository(session),
            SqlAlchemyActivityLog(session),
        ).execute(task_id, title=title, actor_id=actor)


async def add_steps(
    session_factory: SessionFactory, task_id: uuid.UUID, actor: uuid.UUID, titles: list[str]
) -> list[Step]:
    async with transactional_session(session_factory) as session:
        return await AddSteps(
            SqlAlchemyTaskRepository(session),
            SqlAlchemyStepRepository(session),
            SqlAlchemyActivityLog(session),
            SqlAlchemyUserDirectory(session),
        ).execute(task_id, titles=titles, actor_id=actor)


async def reorder(
    session_factory: SessionFactory, task_id: uuid.UUID, step_ids: list[uuid.UUID]
) -> None:
    async with transactional_session(session_factory) as session:
        await ReorderSteps(
            SqlAlchemyTaskRepository(session), SqlAlchemyStepRepository(session)
        ).execute(task_id, step_ids)


async def delete(session_factory: SessionFactory, task_id: uuid.UUID, step_id: uuid.UUID) -> None:
    async with transactional_session(session_factory) as session:
        await DeleteStep(
            SqlAlchemyTaskRepository(session), SqlAlchemyStepRepository(session)
        ).execute(task_id, step_id)


async def test_concurrent_writers_each_get_a_position_of_their_own(
    session_factory: SessionFactory, task_id: uuid.UUID, actor: uuid.UUID
) -> None:
    async with asyncio.timeout(60):
        await asyncio.gather(
            *(add_step(session_factory, task_id, actor, f"step {n}") for n in range(WRITERS)),
            add_steps(session_factory, task_id, actor, ["bulk a", "bulk b", "bulk c"]),
        )

    steps = await steps_of(session_factory, task_id)
    assert [step.position for step in steps] == list(range(WRITERS + 3))
    titles = [step.title for step in steps]
    assert sorted(titles) == sorted(
        [f"step {n}" for n in range(WRITERS)] + ["bulk a", "bulk b", "bulk c"]
    )
    # The three accepted together stayed together, in the order given.
    start = titles.index("bulk a")
    assert titles[start : start + 3] == ["bulk a", "bulk b", "bulk c"]


async def test_concurrent_reorders_leave_one_of_the_orders_asked_for(
    session_factory: SessionFactory, task_id: uuid.UUID, actor: uuid.UUID
) -> None:
    created = await add_steps(session_factory, task_id, actor, [f"s{n}" for n in range(6)])
    ids = [step.id for step in created]
    orders = [ids[n:] + ids[:n] for n in range(6)] + [list(reversed(ids))]

    async with asyncio.timeout(60):
        await asyncio.gather(*(reorder(session_factory, task_id, order) for order in orders))

    steps = await steps_of(session_factory, task_id)
    assert [step.position for step in steps] == list(range(6))
    assert [step.id for step in steps] in orders


async def test_reorders_deletes_and_adds_at_once_keep_positions_dense_and_unique(
    session_factory: SessionFactory, task_id: uuid.UUID, actor: uuid.UUID
) -> None:
    created = await add_steps(session_factory, task_id, actor, [f"s{n}" for n in range(8)])
    ids = [step.id for step in created]

    async def reorder_unless_stale(order: list[uuid.UUID]) -> None:
        # A reorder that waited for a delete or an add names a list that no longer exists:
        # it is refused as a whole, never half applied.
        with contextlib.suppress(InvalidStepOrderError):
            await reorder(session_factory, task_id, order)

    async with asyncio.timeout(60):
        await asyncio.gather(
            reorder_unless_stale(list(reversed(ids))),
            delete(session_factory, task_id, ids[2]),
            add_step(session_factory, task_id, actor, "late"),
            reorder_unless_stale(ids[4:] + ids[:4]),
            delete(session_factory, task_id, ids[5]),
            add_step(session_factory, task_id, actor, "later"),
        )

    steps = await steps_of(session_factory, task_id)
    assert [step.position for step in steps] == list(range(8))
    assert {step.id for step in steps} >= set(ids) - {ids[2], ids[5]}
    assert {"late", "later"} <= {step.title for step in steps}


async def fill_with_steps(
    session_factory: SessionFactory, task_id: uuid.UUID, actor: uuid.UUID, count: int
) -> None:
    for first in range(0, count, MAX_STEPS_AT_ONCE):
        titles = [f"step {n}" for n in range(first, min(first + MAX_STEPS_AT_ONCE, count))]
        await add_steps(session_factory, task_id, actor, titles)


async def test_no_writer_takes_a_task_past_the_steps_it_may_hold(
    session_factory: SessionFactory, task_id: uuid.UUID, actor: uuid.UUID
) -> None:
    """More steps are asked for at once than the task has room for: whoever finds the list
    full is refused, and a batch that does not fit whole adds nothing at all."""
    await fill_with_steps(session_factory, task_id, actor, MAX_STEPS_PER_TASK - 25)
    batches = {"bulk": [f"bulk {n}" for n in range(20)], "draft": [f"draft {n}" for n in range(20)]}

    async with asyncio.timeout(60):
        outcomes = await asyncio.gather(
            *(add_step(session_factory, task_id, actor, f"late {n}") for n in range(12)),
            *(add_steps(session_factory, task_id, actor, titles) for titles in batches.values()),
            return_exceptions=True,
        )

    steps = await steps_of(session_factory, task_id)
    assert len(steps) <= MAX_STEPS_PER_TASK
    assert [step.position for step in steps] == list(range(len(steps)))
    titles = {step.title for step in steps}
    for batch in batches.values():
        assert titles & set(batch) in (set(), set(batch))
    refused = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    assert refused, "the task had no room for all of them"
    for error in refused:
        assert isinstance(error, InvalidStepError)
        assert f"at most {MAX_STEPS_PER_TASK} steps" in str(error)


async def test_the_steps_of_another_task_do_not_wait(
    session_factory: SessionFactory, task_id: uuid.UUID, actor: uuid.UUID
) -> None:
    """The lock is one task's row: steps are added elsewhere while it is held."""
    other = a_task(actor, key=f"CT-{uuid.uuid4().int % 10**8}")
    async with transactional_session(session_factory) as session:
        await SqlAlchemyTaskRepository(session).add(other)

    async with transactional_session(session_factory) as holding:
        assert await SqlAlchemyTaskRepository(holding).get_for_update(task_id) is not None
        async with asyncio.timeout(10):
            step = await add_step(session_factory, other.id, actor, "free")

    assert step.position == 0
