"""The step use cases, with in-memory fakes for every port.

Whatever they do to a task's steps, the positions stay ``0 .. n-1``; what they leave in the
activity log is the wording of ``app.domain.activity_log``.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.application.errors import StepNotFound, TaskNotFound
from app.application.ports.task_tallies import TaskTally
from app.application.use_cases.add_step import AddStep
from app.application.use_cases.add_steps import MAX_STEPS_AT_ONCE, AddSteps
from app.application.use_cases.delete_step import DeleteStep
from app.application.use_cases.list_steps import ListSteps
from app.application.use_cases.reorder_steps import ReorderSteps
from app.application.use_cases.tally_tasks import TallyTasks
from app.application.use_cases.update_step import StepChanges, UpdateStep
from app.domain.step import InvalidStepError, InvalidStepOrderError, Step
from app.domain.task import Task
from tests.activity_fakes import InMemoryActivityLog, InMemoryStepRepository, InMemoryTaskTallies
from tests.auth_fakes import InMemoryUserDirectory, InMemoryUserRepository, a_user
from tests.builders import a_task
from tests.fakes import InMemoryProjectRepository, InMemoryTaskRepository

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class World:
    users: InMemoryUserRepository
    tasks: InMemoryTaskRepository
    steps: InMemoryStepRepository
    activity: InMemoryActivityLog
    actor: uuid.UUID
    task: Task

    @property
    def add_step(self) -> AddStep:
        return AddStep(self.tasks, self.steps, self.activity, clock=lambda: LATER)

    @property
    def add_steps(self) -> AddSteps:
        return AddSteps(
            self.tasks,
            self.steps,
            self.activity,
            InMemoryUserDirectory(self.users),
            clock=lambda: LATER,
        )

    @property
    def update_step(self) -> UpdateStep:
        return UpdateStep(self.tasks, self.steps, self.activity, clock=lambda: LATER)

    @property
    def reorder_steps(self) -> ReorderSteps:
        return ReorderSteps(self.tasks, self.steps, clock=lambda: LATER)

    @property
    def delete_step(self) -> DeleteStep:
        return DeleteStep(self.tasks, self.steps, clock=lambda: LATER)

    @property
    def list_steps(self) -> ListSteps:
        return ListSteps(self.tasks, self.steps)

    async def with_steps(self, *titles: str) -> list[Step]:
        """Steps that are simply there: nothing logged, the task not touched."""
        steps = [
            Step.create(
                step_id=uuid.uuid4(), task_id=self.task.id, title=title, position=n, now=NOW
            )
            for n, title in enumerate(titles)
        ]
        for step in steps:
            await self.steps.add(step)
        return steps

    async def listed(self) -> list[tuple[str, int]]:
        return [(s.title, s.position) for s in await self.steps.list_for_task(self.task.id)]

    async def task_updated_at(self) -> datetime:
        stored = await self.tasks.get(self.task.id)
        assert stored is not None
        return stored.updated_at

    def logged(self) -> list[str]:
        return self.activity.texts(self.task.id)


@pytest.fixture
async def world() -> World:
    users = InMemoryUserRepository()
    tasks = InMemoryTaskRepository(users, InMemoryProjectRepository())
    andres = a_user(full_name="Andres Barradas")
    await users.add(andres)
    task = a_task(andres.id, now=NOW)
    await tasks.add(task)
    return World(
        users, tasks, InMemoryStepRepository(tasks), InMemoryActivityLog(tasks), andres.id, task
    )


# --- add one ------------------------------------------------------------------------------


async def test_a_step_is_appended_last_not_done(world: World) -> None:
    await world.with_steps("first", "second")
    step_id = uuid.uuid4()
    add_step = AddStep(
        world.tasks, world.steps, world.activity, clock=lambda: LATER, new_id=lambda: step_id
    )

    step = await add_step.execute(world.task.id, title="  third ", actor_id=world.actor)

    assert step == Step(
        id=step_id, task_id=world.task.id, title="third", done=False, position=2, created_at=LATER
    )
    assert await world.listed() == [("first", 0), ("second", 1), ("third", 2)]


async def test_adding_a_step_is_logged_and_touches_the_task(world: World) -> None:
    await world.add_step.execute(world.task.id, title="Write the test", actor_id=world.actor)

    assert world.logged() == ["Added step “Write the test”"]
    (entry,) = world.activity.entries
    assert (entry.actor_id, entry.created_at) == (world.actor, LATER)
    assert await world.task_updated_at() == LATER


async def test_a_step_that_breaks_a_rule_is_refused_and_nothing_is_logged(world: World) -> None:
    with pytest.raises(InvalidStepError, match="blank"):
        await world.add_step.execute(world.task.id, title="   ", actor_id=world.actor)

    assert await world.listed() == []
    assert world.logged() == []
    assert await world.task_updated_at() == NOW


async def test_a_step_cannot_be_added_to_a_task_that_does_not_exist(world: World) -> None:
    with pytest.raises(TaskNotFound):
        await world.add_step.execute(uuid.uuid4(), title="orphan", actor_id=world.actor)

    assert world.activity.entries == []


# --- add many -----------------------------------------------------------------------------


async def test_steps_accepted_together_are_appended_in_the_order_given(world: World) -> None:
    await world.with_steps("already here")

    created = await world.add_steps.execute(
        world.task.id, titles=["one", " two ", "three"], actor_id=world.actor
    )

    assert [(s.title, s.position, s.done) for s in created] == [
        ("one", 1, False),
        ("two", 2, False),
        ("three", 3, False),
    ]
    assert await world.listed() == [("already here", 0), ("one", 1), ("two", 2), ("three", 3)]
    assert len({step.id for step in created}) == 3


async def test_steps_accepted_together_leave_one_line_in_the_design_s_words(
    world: World,
) -> None:
    await world.add_steps.execute(world.task.id, titles=["one", "two"], actor_id=world.actor)

    assert world.logged() == ["Drafted 2 steps · added by Andres"]
    assert await world.task_updated_at() == LATER


async def test_one_accepted_step_is_singular(world: World) -> None:
    await world.add_steps.execute(world.task.id, titles=["only"], actor_id=world.actor)

    assert world.logged() == ["Drafted 1 step · added by Andres"]


async def test_one_bad_title_refuses_them_all(world: World) -> None:
    with pytest.raises(InvalidStepError, match="blank"):
        await world.add_steps.execute(
            world.task.id, titles=["fine", "  ", "also fine"], actor_id=world.actor
        )

    assert await world.listed() == []
    assert world.logged() == []


@pytest.mark.parametrize("count", [0, MAX_STEPS_AT_ONCE + 1])
async def test_the_number_of_steps_accepted_at_once_is_limited(world: World, count: int) -> None:
    with pytest.raises(InvalidStepError, match="from 1 to 20"):
        await world.add_steps.execute(
            world.task.id, titles=[f"step {n}" for n in range(count)], actor_id=world.actor
        )

    assert await world.listed() == []


async def test_the_most_steps_that_can_be_accepted_at_once_is_twenty(world: World) -> None:
    titles = [f"step {n}" for n in range(MAX_STEPS_AT_ONCE)]

    await world.add_steps.execute(world.task.id, titles=titles, actor_id=world.actor)

    assert MAX_STEPS_AT_ONCE == 20
    assert await world.listed() == [(title, n) for n, title in enumerate(titles)]


async def test_steps_cannot_be_accepted_for_a_task_that_does_not_exist(world: World) -> None:
    with pytest.raises(TaskNotFound):
        await world.add_steps.execute(uuid.uuid4(), titles=["orphan"], actor_id=world.actor)


# --- rename and tick ------------------------------------------------------------------------


async def test_renaming_a_step_is_silent_but_touches_the_task(world: World) -> None:
    (step,) = await world.with_steps("Write the test")

    renamed = await world.update_step.execute(
        world.task.id, step.id, StepChanges(title=" Write the failing test "), actor_id=world.actor
    )

    assert renamed.title == "Write the failing test"
    assert await world.listed() == [("Write the failing test", 0)]
    assert world.logged() == []
    assert await world.task_updated_at() == LATER


async def test_completing_a_step_is_logged(world: World) -> None:
    (step,) = await world.with_steps("Write the test")

    done = await world.update_step.execute(
        world.task.id, step.id, StepChanges(done=True), actor_id=world.actor
    )

    assert done.done is True
    assert world.logged() == ["Completed step “Write the test”"]
    assert await world.task_updated_at() == LATER


async def test_a_step_renamed_and_completed_at_once_is_logged_under_its_new_title(
    world: World,
) -> None:
    (step,) = await world.with_steps("Write the test")

    await world.update_step.execute(
        world.task.id, step.id, StepChanges(title="Write it first", done=True), actor_id=world.actor
    )

    assert world.logged() == ["Completed step “Write it first”"]


async def test_unticking_a_step_is_silent(world: World) -> None:
    (step,) = await world.with_steps("Write the test")
    await world.update_step.execute(
        world.task.id, step.id, StepChanges(done=True), actor_id=world.actor
    )

    undone = await world.update_step.execute(
        world.task.id, step.id, StepChanges(done=False), actor_id=world.actor
    )

    assert undone.done is False
    assert world.logged() == ["Completed step “Write the test”"]


async def test_a_change_that_alters_nothing_records_nothing_and_touches_nothing(
    world: World,
) -> None:
    (step,) = await world.with_steps("Write the test")
    await world.update_step.execute(
        world.task.id, step.id, StepChanges(done=True), actor_id=world.actor
    )
    world.activity.entries.clear()
    unmoved = UpdateStep(
        world.tasks, world.steps, world.activity, clock=lambda: LATER + timedelta(days=1)
    )

    for same in (StepChanges(), StepChanges(done=True), StepChanges(title=" Write the test ")):
        unchanged = await unmoved.execute(world.task.id, step.id, same, actor_id=world.actor)
        assert (unchanged.title, unchanged.done) == ("Write the test", True)

    assert world.logged() == []
    assert await world.task_updated_at() == LATER


async def test_a_bad_title_is_refused_and_the_step_stays(world: World) -> None:
    (step,) = await world.with_steps("Write the test")

    with pytest.raises(InvalidStepError, match="at most 200"):
        await world.update_step.execute(
            world.task.id, step.id, StepChanges(title="x" * 201, done=True), actor_id=world.actor
        )

    assert [(s.title, s.done) for s in await world.steps.list_for_task(world.task.id)] == [
        ("Write the test", False)
    ]
    assert world.logged() == []


async def test_a_step_is_only_found_under_its_own_task(world: World) -> None:
    (step,) = await world.with_steps("Write the test")
    other = a_task(world.actor)
    await world.tasks.add(other)

    for task_id, step_id in ((other.id, step.id), (world.task.id, uuid.uuid4())):
        with pytest.raises(StepNotFound):
            await world.update_step.execute(
                task_id, step_id, StepChanges(done=True), actor_id=world.actor
            )
        with pytest.raises(StepNotFound):
            await world.delete_step.execute(task_id, step_id)
    with pytest.raises(TaskNotFound):
        await world.update_step.execute(
            uuid.uuid4(), step.id, StepChanges(done=True), actor_id=world.actor
        )
    with pytest.raises(TaskNotFound):
        await world.delete_step.execute(uuid.uuid4(), step.id)

    assert await world.listed() == [("Write the test", 0)]


# --- reorder ------------------------------------------------------------------------------


async def test_steps_take_the_order_they_are_given(world: World) -> None:
    a, b, c = await world.with_steps("a", "b", "c")

    ordered = await world.reorder_steps.execute(world.task.id, [c.id, a.id, b.id])

    assert [(s.title, s.position) for s in ordered] == [("c", 0), ("a", 1), ("b", 2)]
    assert await world.listed() == [("c", 0), ("a", 1), ("b", 2)]
    assert world.logged() == []
    assert await world.task_updated_at() == LATER


async def test_the_order_they_already_have_touches_nothing(world: World) -> None:
    a, b = await world.with_steps("a", "b")

    await world.reorder_steps.execute(world.task.id, [a.id, b.id])

    assert await world.task_updated_at() == NOW


async def test_an_order_that_is_not_every_step_exactly_once_is_refused(world: World) -> None:
    a, b = await world.with_steps("a", "b")

    for ids in ([a.id], [a.id, a.id], [a.id, b.id, uuid.uuid4()]):
        with pytest.raises(InvalidStepOrderError):
            await world.reorder_steps.execute(world.task.id, ids)

    assert await world.listed() == [("a", 0), ("b", 1)]
    with pytest.raises(TaskNotFound):
        await world.reorder_steps.execute(uuid.uuid4(), [a.id, b.id])


# --- delete -------------------------------------------------------------------------------


async def test_deleting_a_step_closes_the_gap(world: World) -> None:
    _, b, _, _ = await world.with_steps("a", "b", "c", "d")

    await world.delete_step.execute(world.task.id, b.id)

    assert await world.listed() == [("a", 0), ("c", 1), ("d", 2)]
    assert world.logged() == []
    assert await world.task_updated_at() == LATER


async def test_positions_stay_dense_whatever_is_done_in_whatever_order(world: World) -> None:
    for n in range(4):
        await world.add_step.execute(world.task.id, title=f"s{n}", actor_id=world.actor)
    steps = list(await world.steps.list_for_task(world.task.id))
    await world.reorder_steps.execute(world.task.id, [s.id for s in reversed(steps)])
    await world.delete_step.execute(world.task.id, steps[3].id)
    await world.add_steps.execute(world.task.id, titles=["s4", "s5"], actor_id=world.actor)
    await world.delete_step.execute(world.task.id, steps[0].id)

    assert await world.listed() == [("s2", 0), ("s1", 1), ("s4", 2), ("s5", 3)]


# --- read ---------------------------------------------------------------------------------


async def test_the_steps_of_a_task_are_listed_in_order(world: World) -> None:
    await world.with_steps("a", "b")

    assert [s.title for s in await world.list_steps.execute(world.task.id)] == ["a", "b"]
    with pytest.raises(TaskNotFound):
        await world.list_steps.execute(uuid.uuid4())


async def test_tasks_are_tallied_together(world: World) -> None:
    (step,) = await world.with_steps("a")
    await world.update_step.execute(
        world.task.id, step.id, StepChanges(done=True), actor_id=world.actor
    )
    nobody = uuid.uuid4()

    tallies = await TallyTasks(InMemoryTaskTallies(world.steps, world.activity)).execute(
        [world.task.id, nobody]
    )

    assert dict(tallies) == {world.task.id: TaskTally(1, 1, 0), nobody: TaskTally()}
