"""Hand-written test doubles for the step and activity ports.

They pass the same contract suites as the PostgreSQL adapters (``tests/contract``).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace

from app.application.errors import StepNotFound
from app.application.ports.activity_feed import ActivityItem, ActivityPage
from app.application.ports.attachment_repository import AttachmentRepository
from app.application.ports.task_tallies import TaskTally
from app.domain.activity import ActivityEntry, ActivityKind, Actor
from app.domain.step import Step
from tests.fakes import InMemoryTaskRepository


class InMemoryStepRepository:
    """StepRepository fake. Steps are copied on the way in and out, as a database would, so
    a change is only stored by an explicit ``update``."""

    def __init__(self, tasks: InMemoryTaskRepository) -> None:
        self._steps: dict[uuid.UUID, Step] = {}
        tasks.on_delete.append(self._forget_task)

    async def add(self, step: Step) -> None:
        self._steps[step.id] = replace(step)

    async def list_for_task(self, task_id: uuid.UUID) -> Sequence[Step]:
        found = [step for step in self._steps.values() if step.task_id == task_id]
        return [replace(step) for step in sorted(found, key=lambda step: step.position)]

    async def update(self, step: Step) -> None:
        if step.id not in self._steps:
            raise StepNotFound(step.id)
        self._steps[step.id] = replace(step)

    async def delete(self, step_id: uuid.UUID) -> None:
        if step_id not in self._steps:
            raise StepNotFound(step_id)
        del self._steps[step_id]

    def _forget_task(self, task_id: uuid.UUID) -> None:
        """What ``ON DELETE CASCADE`` does when a task is deleted."""
        self._steps = {k: step for k, step in self._steps.items() if step.task_id != task_id}


class InMemoryActivityLog:
    """ActivityRecorder and ActivityFeed fake over one list, in the order recorded.

    It names actors from the users fake, the way the real feed joins the users table.
    """

    def __init__(self, tasks: InMemoryTaskRepository) -> None:
        self._users = tasks.users
        self.entries: list[ActivityEntry] = []
        tasks.on_delete.append(self._forget_task)

    async def record(self, entry: ActivityEntry) -> None:
        self.entries.append(entry)

    async def page(self, task_id: uuid.UUID, *, limit: int, offset: int) -> ActivityPage:
        recorded = [
            (entry.created_at, index, entry)
            for index, entry in enumerate(self.entries)
            if entry.task_id == task_id
        ]
        newest_first = [entry for _, _, entry in sorted(recorded, reverse=True)]
        items = [
            ActivityItem(entry, await self._actor(entry.actor_id))
            for entry in newest_first[offset : offset + limit]
        ]
        return ActivityPage(items=items, total=len(newest_first))

    async def _actor(self, actor_id: uuid.UUID) -> Actor:
        user = await self._users.get_by_id(actor_id)
        if user is None:
            raise AssertionError(f"activity by {actor_id}, who is not a stored user")
        return Actor(id=user.id, full_name=user.full_name)

    def texts(self, task_id: uuid.UUID, kind: ActivityKind = ActivityKind.LOG) -> list[str]:
        """Not part of the port: what was recorded for a task, oldest first."""
        return [e.text for e in self.entries if e.task_id == task_id and e.kind is kind]

    def _forget_task(self, task_id: uuid.UUID) -> None:
        """What ``ON DELETE CASCADE`` does when a task is deleted."""
        self.entries = [entry for entry in self.entries if entry.task_id != task_id]


class InMemoryTaskTallies:
    """TaskTallies fake over the step, activity and attachment stores."""

    def __init__(
        self,
        steps: InMemoryStepRepository,
        activity: InMemoryActivityLog,
        attachments: AttachmentRepository,
    ) -> None:
        self._steps = steps
        self._activity = activity
        self._attachments = attachments

    async def for_tasks(self, task_ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, TaskTally]:
        tallies: dict[uuid.UUID, TaskTally] = {}
        attachments = await self._attachments.count_by_task(task_ids)
        for task_id in task_ids:
            steps = await self._steps.list_for_task(task_id)
            tallies[task_id] = TaskTally(
                steps_total=len(steps),
                steps_done=sum(1 for step in steps if step.done),
                comments_count=len(self._activity.texts(task_id, ActivityKind.COMMENT)),
                attachments_count=attachments[task_id],
            )
        return tallies
