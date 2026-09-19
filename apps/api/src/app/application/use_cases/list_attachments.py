import uuid
from collections.abc import Collection, Mapping, Sequence

from app.application.ports.attachment_repository import AttachmentRepository
from app.domain.attachment import Attachment


class ListAttachments:
    """What the task representations say about attachments: the list, or just how many."""

    def __init__(self, attachments: AttachmentRepository) -> None:
        self._attachments = attachments

    async def execute(self, task_id: uuid.UUID) -> Sequence[Attachment]:
        """Oldest first. A task that is not stored has none."""
        return await self._attachments.list_for_task(task_id)

    async def count(self, task_ids: Collection[uuid.UUID]) -> Mapping[uuid.UUID, int]:
        """Every id asked about is a key; one statement for a whole page of tasks."""
        return await self._attachments.count_by_task(task_ids)
