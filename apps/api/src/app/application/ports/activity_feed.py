import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.domain.activity import ActivityEntry, Actor

DEFAULT_ACTIVITY_LIMIT = 50
MAX_ACTIVITY_LIMIT = 200


@dataclass(frozen=True, slots=True)
class ActivityItem:
    """An entry and who it is by: a name for the timeline, never an email."""

    entry: ActivityEntry
    actor: Actor


@dataclass(frozen=True, slots=True)
class ActivityPage:
    items: Sequence[ActivityItem]
    total: int  # how many entries the task has, whatever the page


class ActivityFeed(Protocol):
    """Reads a task's activity. Separate from ``ActivityRecorder``: whoever records an event
    (a task use case, an attachment use case) never needs to read the timeline."""

    async def page(self, task_id: uuid.UUID, *, limit: int, offset: int) -> ActivityPage:
        """One page, newest first; entries of the same instant, last recorded first. The
        actor is named whether or not that user is still active. A task without entries,
        or no such task, is an empty page."""
        ...
