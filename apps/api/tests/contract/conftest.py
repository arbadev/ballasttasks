"""One store for the suites of the ports that hang off a task: steps, activity and tallies.

Steps and activity entries reference a task, and an entry references the user it is by, so
every adapter is paired with the repositories that write what it points at. The in-memory
fakes run everywhere; the SQLAlchemy adapters run the same cases under the ``integration``
marker, in a transaction that is rolled back, in a database nothing is ever committed to.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.activity_feed import ActivityFeed
from app.application.ports.activity_recorder import ActivityRecorder
from app.application.ports.step_repository import StepRepository
from app.application.ports.task_repository import TaskRepository
from app.application.ports.task_tallies import TaskTallies
from app.application.ports.user_repository import UserRepository
from app.domain.task import Task
from app.domain.user import User
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.activity import SqlAlchemyActivityLog
from app.infrastructure.db.repositories.step import SqlAlchemyStepRepository
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.repositories.task_tallies import SqlAlchemyTaskTallies
from app.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from tests.activity_fakes import InMemoryActivityLog, InMemoryStepRepository, InMemoryTaskTallies
from tests.auth_fakes import InMemoryUserRepository, a_user
from tests.builders import a_task
from tests.fakes import InMemoryProjectRepository, InMemoryTaskRepository

TASK_SIDE_ADAPTERS = [
    pytest.param("in-memory"),
    pytest.param("sqlalchemy-postgresql", marks=pytest.mark.integration),
]


@dataclass(frozen=True, slots=True)
class TaskSideStore:
    users: UserRepository
    tasks: TaskRepository
    steps: StepRepository
    recorder: ActivityRecorder
    feed: ActivityFeed
    tallies: TaskTallies

    async def a_stored_user(self, **overrides: object) -> User:
        user = a_user(**overrides)  # type: ignore[arg-type]
        await self.users.add(user)
        return user

    async def a_stored_task(self, creator: User | None = None) -> Task:
        task = a_task((creator or await self.a_stored_user()).id)
        await self.tasks.add(task)
        return task


@pytest.fixture(params=TASK_SIDE_ADAPTERS)
async def task_side(request: pytest.FixtureRequest) -> AsyncIterator[TaskSideStore]:
    if request.param == "in-memory":
        users = InMemoryUserRepository()
        tasks = InMemoryTaskRepository(users, InMemoryProjectRepository())
        steps, log = InMemoryStepRepository(tasks), InMemoryActivityLog(tasks)
        yield TaskSideStore(users, tasks, steps, log, log, InMemoryTaskTallies(steps, log))
        return

    engine = create_engine(request.getfixturevalue("pristine_database_url"))
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            sql_log = SqlAlchemyActivityLog(session)
            yield TaskSideStore(
                SqlAlchemyUserRepository(session),
                SqlAlchemyTaskRepository(session),
                SqlAlchemyStepRepository(session),
                sql_log,
                sql_log,
                SqlAlchemyTaskTallies(session),
            )
        await transaction.rollback()
    await engine.dispose()
