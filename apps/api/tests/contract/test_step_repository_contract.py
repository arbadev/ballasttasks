"""Contract every StepRepository adapter must honour (Liskov). The store: ``conftest.py``."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.application.errors import StepNotFound
from app.domain.step import Step
from tests.contract.conftest import TaskSideStore

# PostgreSQL keeps microseconds, so this value survives a round trip unchanged.
CREATED = datetime(2026, 1, 5, 9, 0, 0, 123456, tzinfo=UTC)


def a_step(task_id: uuid.UUID, position: int, title: str = "Write the failing test") -> Step:
    return Step.create(
        step_id=uuid.uuid4(), task_id=task_id, title=title, position=position, now=CREATED
    )


async def test_a_task_without_steps_has_none(task_side: TaskSideStore) -> None:
    task = await task_side.a_stored_task()

    assert list(await task_side.steps.list_for_task(task.id)) == []
    assert list(await task_side.steps.list_for_task(uuid.uuid4())) == []


async def test_a_stored_step_comes_back_as_it_was(task_side: TaskSideStore) -> None:
    task = await task_side.a_stored_task()
    step = a_step(task.id, 0, "Ünïcode “quoted” → title")

    await task_side.steps.add(step)

    assert list(await task_side.steps.list_for_task(task.id)) == [step]


async def test_steps_are_listed_by_position_whatever_order_they_arrived_in(
    task_side: TaskSideStore,
) -> None:
    task = await task_side.a_stored_task()
    third, first, second = a_step(task.id, 2, "c"), a_step(task.id, 0, "a"), a_step(task.id, 1, "b")
    for step in (third, first, second):
        await task_side.steps.add(step)

    assert list(await task_side.steps.list_for_task(task.id)) == [first, second, third]


async def test_only_the_steps_of_that_task_are_listed(task_side: TaskSideStore) -> None:
    creator = await task_side.a_stored_user()
    task, other = await task_side.a_stored_task(creator), await task_side.a_stored_task(creator)
    mine, theirs = a_step(task.id, 0), a_step(other.id, 0)
    await task_side.steps.add(mine)
    await task_side.steps.add(theirs)

    assert list(await task_side.steps.list_for_task(task.id)) == [mine]
    assert list(await task_side.steps.list_for_task(other.id)) == [theirs]


async def test_a_returned_step_is_detached_until_it_is_updated(task_side: TaskSideStore) -> None:
    task = await task_side.a_stored_task()
    await task_side.steps.add(a_step(task.id, 0))

    (loaded,) = await task_side.steps.list_for_task(task.id)
    loaded.rename("Changed my mind")
    loaded.mark(done=True)

    (stored,) = await task_side.steps.list_for_task(task.id)
    assert (stored.title, stored.done) == ("Write the failing test", False)


async def test_update_stores_title_done_and_position(task_side: TaskSideStore) -> None:
    task = await task_side.a_stored_task()
    step = a_step(task.id, 0)
    await task_side.steps.add(step)

    changed = replace(step, title="Make it pass", done=True, position=4)
    await task_side.steps.update(changed)

    assert list(await task_side.steps.list_for_task(task.id)) == [changed]


async def test_two_steps_can_swap_places_within_one_unit_of_work(
    task_side: TaskSideStore,
) -> None:
    """Positions are unique per task, but only when the unit of work ends: a reorder passes
    through states where two steps share a position."""
    task = await task_side.a_stored_task()
    first, second = a_step(task.id, 0, "first"), a_step(task.id, 1, "second")
    await task_side.steps.add(first)
    await task_side.steps.add(second)

    await task_side.steps.update(replace(first, position=1))
    await task_side.steps.update(replace(second, position=0))

    listed = await task_side.steps.list_for_task(task.id)
    assert [(step.title, step.position) for step in listed] == [("second", 0), ("first", 1)]


async def test_updating_a_step_nobody_stored_is_not_found(task_side: TaskSideStore) -> None:
    task = await task_side.a_stored_task()
    ghost = a_step(task.id, 0)

    with pytest.raises(StepNotFound) as raised:
        await task_side.steps.update(ghost)

    assert raised.value.step_id == ghost.id


async def test_a_deleted_step_is_gone_and_the_others_stay(task_side: TaskSideStore) -> None:
    task = await task_side.a_stored_task()
    kept, removed = a_step(task.id, 0, "kept"), a_step(task.id, 1, "removed")
    await task_side.steps.add(kept)
    await task_side.steps.add(removed)

    await task_side.steps.delete(removed.id)

    assert list(await task_side.steps.list_for_task(task.id)) == [kept]
    with pytest.raises(StepNotFound):
        await task_side.steps.delete(removed.id)


async def test_deleting_a_task_deletes_its_steps_and_only_its_steps(
    task_side: TaskSideStore,
) -> None:
    creator = await task_side.a_stored_user()
    task, other = await task_side.a_stored_task(creator), await task_side.a_stored_task(creator)
    doomed, survivor = a_step(task.id, 0), a_step(other.id, 0)
    await task_side.steps.add(doomed)
    await task_side.steps.add(survivor)

    await task_side.tasks.delete(task.id)

    assert list(await task_side.steps.list_for_task(task.id)) == []
    assert list(await task_side.steps.list_for_task(other.id)) == [survivor]
    with pytest.raises(StepNotFound):
        await task_side.steps.update(doomed)
