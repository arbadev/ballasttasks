import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TaskTally:
    """The numbers a task row shows next to its title: ``2/5`` steps, 3 comments."""

    steps_total: int = 0
    steps_done: int = 0
    comments_count: int = 0


class TaskTallies(Protocol):
    """Counts the steps and the comments of many tasks at once."""

    async def for_tasks(self, task_ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, TaskTally]:
        """A tally for every id asked for (zeros for a task with nothing, or no such task).

        One statement however many ids there are, and none at all for no ids: a page of the
        task list never costs a query per task.
        """
        ...
