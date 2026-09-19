import uuid
from datetime import UTC, datetime

import pytest

from app.domain.step import (
    STEP_TITLE_MAX_LENGTH,
    InvalidStepError,
    InvalidStepOrderError,
    Step,
    close_gap,
    in_order,
)

CREATED = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
TASK = uuid.uuid4()


def new_step(title: str = "Write the failing test", *, position: int = 0) -> Step:
    return Step.create(
        step_id=uuid.uuid4(), task_id=TASK, title=title, position=position, now=CREATED
    )


def test_a_new_step_is_not_done_and_keeps_where_it_was_put() -> None:
    step_id = uuid.uuid4()

    step = Step.create(
        step_id=step_id, task_id=TASK, title="Write the failing test", position=3, now=CREATED
    )

    assert step.id == step_id
    assert step.task_id == TASK
    assert step.title == "Write the failing test"
    assert step.done is False
    assert step.position == 3
    assert step.created_at == CREATED


def test_the_title_is_trimmed() -> None:
    assert new_step("  Write the failing test \n").title == "Write the failing test"


@pytest.mark.parametrize("title", ["", "   ", "\t\n"])
def test_a_blank_title_is_refused(title: str) -> None:
    with pytest.raises(InvalidStepError, match="blank"):
        new_step(title)


def test_the_title_has_a_maximum_length_counted_after_trimming() -> None:
    assert len(new_step(" " + "x" * STEP_TITLE_MAX_LENGTH + " ").title) == STEP_TITLE_MAX_LENGTH
    with pytest.raises(InvalidStepError, match="at most 200"):
        new_step("x" * (STEP_TITLE_MAX_LENGTH + 1))


def test_a_title_with_a_nul_character_is_refused() -> None:
    with pytest.raises(InvalidStepError, match="NUL"):
        new_step("before\x00after")


def test_a_negative_position_is_refused() -> None:
    with pytest.raises(InvalidStepError, match="position"):
        new_step(position=-1)


def test_a_naive_timestamp_is_refused() -> None:
    with pytest.raises(InvalidStepError, match="timezone-aware"):
        Step.create(
            step_id=uuid.uuid4(),
            task_id=TASK,
            title="Write the failing test",
            position=0,
            now=datetime(2026, 1, 5, 9, 0),
        )


def test_a_stored_step_is_held_to_the_same_rules() -> None:
    with pytest.raises(InvalidStepError, match="blank"):
        Step(id=uuid.uuid4(), task_id=TASK, title=" ", done=True, position=0, created_at=CREATED)


def test_renaming_applies_the_title_rules() -> None:
    step = new_step()

    step.rename("  Make it pass ")

    assert step.title == "Make it pass"
    with pytest.raises(InvalidStepError, match="blank"):
        step.rename("   ")
    assert step.title == "Make it pass"


def test_marking_says_whether_anything_changed() -> None:
    step = new_step()

    assert step.mark(done=True) is True
    assert step.done is True
    assert step.mark(done=True) is False
    assert step.mark(done=False) is True
    assert step.done is False


def test_in_order_gives_every_step_the_position_of_its_id() -> None:
    first, second, third = (new_step(f"step {n}", position=n) for n in range(3))

    ordered = in_order([first, second, third], [third.id, first.id, second.id])

    assert [step.id for step in ordered] == [third.id, first.id, second.id]
    assert [step.position for step in ordered] == [0, 1, 2]


def test_in_order_refuses_anything_but_every_step_exactly_once() -> None:
    first, second = new_step("one", position=0), new_step("two", position=1)

    for ids in (
        [first.id],
        [first.id, first.id],
        [first.id, second.id, uuid.uuid4()],
        [first.id, uuid.uuid4()],
        [],
    ):
        with pytest.raises(InvalidStepOrderError, match="every step of the task exactly once"):
            in_order([first, second], ids)
    assert (first.position, second.position) == (0, 1)


def test_in_order_of_no_steps_is_no_steps() -> None:
    assert in_order([], []) == []


def test_close_gap_moves_the_steps_after_a_removed_one_up() -> None:
    steps = [new_step(f"step {n}", position=n) for n in range(4)]
    removed = steps.pop(1)

    moved = close_gap(steps, removed)

    assert [step.position for step in steps] == [0, 1, 2]
    assert [step.title for step in moved] == ["step 2", "step 3"]
