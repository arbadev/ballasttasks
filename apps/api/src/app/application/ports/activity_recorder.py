from typing import Protocol

from app.domain.activity import ActivityEntry


class ActivityRecorder(Protocol):
    """Appends to a task's activity. The ONE way application code writes to the timeline.

    It works inside the unit of work it was built in and never commits, so an entry is
    stored exactly when the change it describes is: both commit, or neither does. Entries
    are append-only; there is no update and no delete.

    A use case that changed a task builds the entry (``ActivityEntry.log`` with a text from
    ``app.domain.activity_log``, or ``ActivityEntry.comment``) and records it; a change that
    altered nothing records nothing. ``task_id`` and ``actor_id`` must name a stored task and
    a stored user: the use case has just loaded the one and authenticated the other.
    """

    async def record(self, entry: ActivityEntry) -> None:
        """Store the entry."""
        ...
