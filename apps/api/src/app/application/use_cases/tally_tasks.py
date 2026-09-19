import uuid
from collections.abc import Mapping, Sequence

from app.application.ports.task_tallies import TaskTallies, TaskTally


class TallyTasks:
    """``steps_total``, ``steps_done`` and ``comments_count`` for the tasks of one response,
    asked for together so a page of the list never costs a query per task."""

    def __init__(self, tallies: TaskTallies) -> None:
        self._tallies = tallies

    async def execute(self, task_ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, TaskTally]:
        return await self._tallies.for_tasks(task_ids)
