"""The SQL urgency expression, value by value, against the design's own function.

The contract suite already holds the ORDER to the design; this holds the NUMBERS, so a
change that keeps the order of today's table but drifts from the formula is still caught.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.task_query import TaskSignal
from app.domain.attention import assess
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.models.task import TaskModel
from app.infrastructure.db.repositories.project import SqlAlchemyProjectRepository
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.repositories.task_queries import signal_condition, urgency_score
from tests.builders import a_project
from tests.postgres import INSERT_USER, user_row
from tests.urgency_cases import CASES, TODAY

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(pristine_database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_engine(pristine_database_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


async def test_sql_urgency_and_signals_equal_the_design_function_for_every_case(
    session: AsyncSession,
) -> None:
    creator = user_row()
    await session.execute(INSERT_USER, creator)
    project = a_project(name="Urgency", key="UR")
    await SqlAlchemyProjectRepository(session).add(project)
    repository = SqlAlchemyTaskRepository(session)
    expected = {}
    for number, case in enumerate(CASES, start=1):
        task = case.task(created_by=creator["id"], project_id=project.id, number=number)
        await repository.add(task)
        expected[task.id] = (case, task)

    rows = await session.execute(
        select(
            TaskModel.id,
            urgency_score(TODAY),
            signal_condition(TaskSignal.OVERDUE, TODAY),
            signal_condition(TaskSignal.P0_AT_RISK, TODAY),
            signal_condition(TaskSignal.DUE_SOON, TODAY),
            signal_condition(TaskSignal.NEEDS_OWNER, TODAY),
        ).where(TaskModel.project_id == project.id)
    )

    seen: set[uuid.UUID] = set()
    for task_id, score, overdue, at_risk, due_soon, needs_owner in rows:
        case, task = expected[task_id]
        design = case.expected
        assert float(score) == pytest.approx(design.score), case.label
        assert float(score) == pytest.approx(assess(task, today=TODAY).urgency), case.label
        assert (overdue, at_risk, due_soon, needs_owner) == (
            design.overdue,
            design.critical,
            design.today or design.soon,
            design.unassigned,
        ), case.label
        seen.add(task_id)
    assert len(seen) == len(CASES)
