import uuid
from collections.abc import Sequence
from typing import Protocol

from app.domain.step import Step


class StepRepository(Protocol):
    """Stores the steps of tasks. Returned steps are detached: a change is stored only by
    ``update``.

    The store keeps positions as it is given them; keeping a task's positions dense and
    unique is the use cases' job (``app.domain.step``), done while they hold the task with
    ``TaskRepository.get_for_update`` so two writers never renumber the same list at once.
    Deleting a task deletes its steps.
    """

    async def add(self, step: Step) -> None:
        """Store a new step of a stored task."""
        ...

    async def list_for_task(self, task_id: uuid.UUID) -> Sequence[Step]:
        """The task's steps by position; none for a task without steps or an unknown task."""
        ...

    async def update(self, step: Step) -> None:
        """Store the title, the done flag and the position. Raises ``StepNotFound``."""
        ...

    async def delete(self, step_id: uuid.UUID) -> None:
        """Remove the step. Raises ``StepNotFound``."""
        ...
