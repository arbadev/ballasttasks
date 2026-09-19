import uuid
from collections.abc import Collection, Mapping, Sequence
from typing import Protocol

from app.domain.attachment import Attachment


class AttachmentRepository(Protocol):
    """Stores the attachments of tasks. An attachment never changes: it is added or deleted.

    An attachment belongs to a stored task and goes when the task goes: deleting a task
    through the ``TaskRepository`` removes its attachments from this store as well. The
    stored FILE of an attachment is not this store's business (see ``FileStorage``).
    """

    async def add(self, attachment: Attachment) -> None:
        """Store a new attachment. Raises ``TaskNotFound`` when its task is not stored; the
        store keeps nothing and stays usable."""
        ...

    async def get(self, attachment_id: uuid.UUID) -> Attachment | None:
        """The attachment with that id, or ``None``."""
        ...

    async def list_for_task(self, task_id: uuid.UUID) -> Sequence[Attachment]:
        """The attachments of one task, oldest first (``created_at``, then ``id``)."""
        ...

    async def count_by_task(self, task_ids: Collection[uuid.UUID]) -> Mapping[uuid.UUID, int]:
        """How many attachments each of these tasks has: every id asked about is a key, with
        ``0`` for a task that has none. One statement however many tasks are asked about."""
        ...

    async def delete(self, attachment_id: uuid.UUID) -> None:
        """Remove the attachment. Raises ``AttachmentNotFound``."""
        ...
