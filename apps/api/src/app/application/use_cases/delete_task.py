import uuid

from app.application.errors import TaskNotFound
from app.application.file_changes import FileChanges
from app.application.ports.attachment_repository import AttachmentRepository
from app.application.ports.task_repository import TaskRepository


class DeleteTask:
    def __init__(
        self, tasks: TaskRepository, attachments: AttachmentRepository, files: FileChanges
    ) -> None:
        self._tasks = tasks
        self._attachments = attachments
        self._files = files

    async def execute(self, task_id: uuid.UUID) -> None:
        """Lock against concurrent attachments; remove their files only after commit."""
        if await self._tasks.get_for_update(task_id) is None:
            raise TaskNotFound(task_id)
        attachments = await self._attachments.list_for_task(task_id)
        await self._tasks.delete(task_id)
        for attachment in attachments:
            if attachment.storage_key is not None:
                self._files.remove_after_commit(attachment.storage_key)
