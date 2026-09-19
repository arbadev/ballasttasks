import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.application.clock import Clock, today_utc, utc_now
from app.application.ports.project_repository import ProjectOverview, ProjectRepository
from app.application.ports.task_repository import TaskRepository
from app.application.task_query import OPEN_STATUSES, SignalCounts, TaskCounts, TaskFilter


@dataclass(frozen=True, slots=True)
class TaskSummary:
    counts: TaskCounts
    projects: Sequence[ProjectOverview]
    signals: SignalCounts


class SummariseTasks:
    """The numbers around the task list: the sidebar and the Attention strip.

    As in the design (lines 726 and 743 to 744) the sidebar counts the open tasks of the
    whole workspace, whatever is filtered, and the strip describes the open tasks in view.
    The strip follows every filter except two: the status (it is about open work even while
    the list shows done tasks) and the selected signal (choosing one chip must not blank the
    others). A caller that sends only ``project_id`` gets exactly the design's strip.
    """

    def __init__(
        self, tasks: TaskRepository, projects: ProjectRepository, *, clock: Clock = utc_now
    ) -> None:
        self._tasks = tasks
        self._projects = projects
        self._clock = clock

    async def execute(self, task_filter: TaskFilter, *, viewer_id: uuid.UUID) -> TaskSummary:
        today = today_utc(self._clock)
        in_view = replace(task_filter, statuses=OPEN_STATUSES, signal=None)
        return TaskSummary(
            counts=await self._tasks.count_open(viewer_id=viewer_id, today=today),
            projects=await self._projects.overviews(),
            signals=await self._tasks.count_signals(in_view, today=today),
        )
