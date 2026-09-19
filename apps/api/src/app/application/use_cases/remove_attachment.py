import uuid

from app.application.clock import Clock, utc_now
from app.application.errors import AttachmentNotFound, TaskNotFound
from app.application.file_changes import FileChanges
from app.application.ports.attachment_repository import AttachmentRepository
from app.application.ports.task_repository import TaskRepository


class RemoveAttachment:
    def __init__(
        self,
        tasks: TaskRepository,
        attachments: AttachmentRepository,
        files: FileChanges,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._tasks = tasks
        self._attachments = attachments
        self._files = files
        self._clock = clock

    async def execute(self, task_id: uuid.UUID, attachment_id: uuid.UUID) -> None:
        """Raises ``TaskNotFound``, and ``AttachmentNotFound`` also when the attachment
        belongs to another task: an attachment is only reached through its own task."""
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        attachment = await self._attachments.get(attachment_id)
        if attachment is None or attachment.task_id != task_id:
            raise AttachmentNotFound(attachment_id)
        await self._attachments.delete(attachment_id)
        if attachment.storage_key is not None:
            self._files.remove_after_commit(attachment.storage_key)
        task.touch(now=self._clock())
        await self._tasks.update(task)
