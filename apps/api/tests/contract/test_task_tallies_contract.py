"""Contract every TaskTallies adapter must honour (Liskov). The store: ``conftest.py``.

That the PostgreSQL adapter answers with ONE statement is asserted where statements can be
counted: ``tests/integration/test_steps_activity_api.py``.
"""

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from app.application.ports.task_tallies import TaskTally
from app.domain.activity import ActivityEntry
from app.domain.step import Step
from tests.contract.conftest import TaskSideStore

NOW = datetime(2026, 1, 5, 9, 0, 0, 123456, tzinfo=UTC)


async def add_steps(task_side: TaskSideStore, task_id: uuid.UUID, *, done: int, todo: int) -> None:
    for position in range(done + todo):
        step = Step.create(
            step_id=uuid.uuid4(), task_id=task_id, title="a step", position=position, now=NOW
        )
        await task_side.steps.add(replace(step, done=position < done))


async def test_no_ids_is_no_tallies(task_side: TaskSideStore) -> None:
    assert dict(await task_side.tallies.for_tasks([])) == {}


async def test_a_task_with_nothing_and_an_unknown_task_are_all_zeros(
    task_side: TaskSideStore,
) -> None:
    task, nobody = await task_side.a_stored_task(), uuid.uuid4()

    tallies = await task_side.tallies.for_tasks([task.id, nobody])

    assert dict(tallies) == {task.id: TaskTally(0, 0, 0), nobody: TaskTally(0, 0, 0)}


async def test_steps_are_counted_in_all_and_done(task_side: TaskSideStore) -> None:
    task = await task_side.a_stored_task()
    await add_steps(task_side, task.id, done=2, todo=3)

    tallies = await task_side.tallies.for_tasks([task.id])

    assert tallies[task.id] == TaskTally(steps_total=5, steps_done=2, comments_count=0)


async def test_comments_are_counted_and_log_lines_are_not(task_side: TaskSideStore) -> None:
    user = await task_side.a_stored_user()
    task = await task_side.a_stored_task(user)
    for make, text in (
        (ActivityEntry.log, "Created the task"),
        (ActivityEntry.comment, "first"),
        (ActivityEntry.log, "Moved To Do → Done"),
        (ActivityEntry.comment, "second"),
    ):
        await task_side.recorder.record(
            make(entry_id=uuid.uuid4(), task_id=task.id, actor_id=user.id, text=text, now=NOW)
        )

    tallies = await task_side.tallies.for_tasks([task.id])

    assert tallies[task.id] == TaskTally(steps_total=0, steps_done=0, comments_count=2)


async def test_every_task_gets_its_own_numbers(task_side: TaskSideStore) -> None:
    """Steps and comments of one task must not multiply each other, nor leak into another."""
    user = await task_side.a_stored_user()
    busy, quiet, empty = [await task_side.a_stored_task(user) for _ in range(3)]
    await add_steps(task_side, busy.id, done=1, todo=2)
    await add_steps(task_side, quiet.id, done=0, todo=1)
    for n in range(4):
        await task_side.recorder.record(
            ActivityEntry.comment(
                entry_id=uuid.uuid4(), task_id=busy.id, actor_id=user.id, text=f"c{n}", now=NOW
            )
        )

    tallies = await task_side.tallies.for_tasks([busy.id, quiet.id, empty.id])

    assert dict(tallies) == {
        busy.id: TaskTally(steps_total=3, steps_done=1, comments_count=4),
        quiet.id: TaskTally(steps_total=1, steps_done=0, comments_count=0),
        empty.id: TaskTally(0, 0, 0),
    }
