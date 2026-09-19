"""A step (subtask) of a task, and the rules that keep a task's steps in order.

Standard library only. A task's steps sit at the positions ``0 .. n-1`` with no gap and no
repeat; ``in_order`` and ``close_gap`` are the only two ways positions change, so that rule
has one home (ADR 0007). A task holds at most ``MAX_STEPS_PER_TASK`` of them, which is what
keeps a task's list, and so every read of it, bounded.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Self

STEP_TITLE_MAX_LENGTH = 200
MAX_STEPS_PER_TASK = 100


class InvalidStepError(ValueError):
    """A step would break one of its rules."""


class InvalidStepOrderError(ValueError):
    """A new order does not name every step of the task exactly once."""

    def __init__(self) -> None:
        super().__init__("step_ids must name every step of the task exactly once")


@dataclass(slots=True)
class Step:
    id: uuid.UUID
    task_id: uuid.UUID
    title: str
    done: bool
    position: int
    created_at: datetime

    def __post_init__(self) -> None:
        self.title = valid_step_title(self.title)
        if type(self.position) is not int or self.position < 0:
            raise InvalidStepError("position must be a whole number, zero or more")
        if self.created_at.utcoffset() is None:
            raise InvalidStepError("timestamps must be timezone-aware")

    @classmethod
    def create(
        cls, *, step_id: uuid.UUID, task_id: uuid.UUID, title: str, position: int, now: datetime
    ) -> Self:
        return cls(
            id=step_id, task_id=task_id, title=title, done=False, position=position, created_at=now
        )

    def rename(self, title: str) -> None:
        self.title = valid_step_title(title)

    def mark(self, *, done: bool) -> bool:
        """``True`` when this changed the step: ticking a ticked step is not an event."""
        changed = self.done != done
        self.done = done
        return changed


def check_room_for(existing: int, adding: int) -> None:
    """Raises ``InvalidStepError``, before any step is built, unless the task can hold
    ``adding`` more steps. A batch that does not fit whole does not fit at all."""
    if existing + adding > MAX_STEPS_PER_TASK:
        raise InvalidStepError(f"a task may hold at most {MAX_STEPS_PER_TASK} steps")


def in_order(steps: Sequence[Step], step_ids: Sequence[uuid.UUID]) -> list[Step]:
    """The same steps in the order of ``step_ids``, each at the position it now has.

    Raises ``InvalidStepOrderError``, before any step is touched, unless ``step_ids`` names
    every one of ``steps`` exactly once.
    """
    by_id = {step.id: step for step in steps}
    if len(step_ids) != len(by_id) or set(step_ids) != set(by_id):
        raise InvalidStepOrderError
    ordered = [by_id[step_id] for step_id in step_ids]
    for position, step in enumerate(ordered):
        step.position = position
    return ordered


def close_gap(remaining: Sequence[Step], removed: Step) -> list[Step]:
    """Move the steps that came after ``removed`` one place up; returns the ones that moved."""
    moved = [step for step in remaining if step.position > removed.position]
    for step in moved:
        step.position -= 1
    return moved


def valid_step_title(title: str) -> str:
    """Normalise a stored step or an unaccepted generated proposal by the same rule."""
    if "\x00" in title:
        raise InvalidStepError("title must not contain the NUL character")
    stripped = title.strip()
    if not stripped:
        raise InvalidStepError("title must not be blank")
    if len(stripped) > STEP_TITLE_MAX_LENGTH:
        raise InvalidStepError(f"title must be at most {STEP_TITLE_MAX_LENGTH} characters")
    return stripped
