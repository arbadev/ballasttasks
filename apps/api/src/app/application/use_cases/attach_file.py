import uuid
from collections.abc import AsyncIterator

from app.application.clock import Clock, utc_now
from app.application.errors import (
    EmptyFileError,
    FileTooLargeError,
    TaskNotFound,
    UnsupportedFileTypeError,
)
from app.application.file_changes import FileChanges
from app.application.ports.attachment_repository import AttachmentRepository
from app.application.ports.file_storage import FileStorage
from app.application.ports.task_repository import TaskRepository
from app.domain.attachment import Attachment
from app.domain.file_type import SNIFF_BYTES, sniff


class AttachFile:
    def __init__(
        self,
        tasks: TaskRepository,
        attachments: AttachmentRepository,
        storage: FileStorage,
        files: FileChanges,
        *,
        max_bytes: int,
        clock: Clock = utc_now,
    ) -> None:
        self._tasks = tasks
        self._attachments = attachments
        self._storage = storage
        self._files = files
        self._max_bytes = max_bytes
        self._clock = clock

    async def execute(
        self,
        task_id: uuid.UUID,
        *,
        file_name: str | None,
        chunks: AsyncIterator[bytes],
        created_by: uuid.UUID,
    ) -> Attachment:
        if await self._tasks.get(task_id) is None:
            raise TaskNotFound(task_id)
        head = bytearray()
        remainder = b""
        size = 0
        async for chunk in chunks:
            size += len(chunk)
            if size > self._max_bytes:
                raise FileTooLargeError(self._max_bytes)
            needed = SNIFF_BYTES - len(head)
            head.extend(chunk[:needed])
            remainder = chunk[needed:]
            if len(head) == SNIFF_BYTES:
                break
        if not head:
            raise EmptyFileError
        file_type = sniff(bytes(head))
        if file_type is None:
            raise UnsupportedFileTypeError

        async def bounded() -> AsyncIterator[bytes]:
            nonlocal size
            yield bytes(head)
            if remainder:
                yield remainder
            async for chunk in chunks:
                size += len(chunk)
                if size > self._max_bytes:
                    raise FileTooLargeError(self._max_bytes)
                yield chunk

        key = uuid.uuid4().hex
        stored = await self._storage.save(key, bounded())
        self._files.written(stored.key)
        # Only lock after upload: a slow sender must not hold a task row hostage.
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        now = self._clock()
        attached = Attachment.file(
            attachment_id=uuid.uuid4(),
            task_id=task_id,
            file_name=file_name,
            file_type=file_type,
            storage_key=stored.key,
            size_bytes=stored.size_bytes,
            created_by=created_by,
            now=now,
        )
        await self._attachments.add(attached)
        task.touch(now=now)
        await self._tasks.update(task)
        return attached
