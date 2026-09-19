"""Attach an uploaded file: two short units of work, with the upload streamed between them.

The client decides how long its body takes to arrive, so nothing may wait for it holding a
database connection. The task is checked in one unit of work, the bytes go to the
``FileStorage`` while none is open, and the row is written in a second one. What was
written is deleted again if anything after it fails, the second unit's commit included, so
a refused or rolled back upload leaves nothing behind (ADR 0008).
"""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from app.application.clock import Clock
from app.application.errors import (
    EmptyFileError,
    FileTooLargeError,
    TaskNotFound,
    UnsupportedFileTypeError,
)
from app.application.file_changes import files_following_the_transaction
from app.application.ports.activity_recorder import ActivityRecorder
from app.application.ports.attachment_repository import AttachmentRepository
from app.application.ports.file_storage import FileStorage
from app.application.ports.task_repository import TaskRepository
from app.application.use_cases.get_task import GetTask
from app.domain import activity_log
from app.domain.activity import ActivityEntry
from app.domain.attachment import Attachment
from app.domain.file_type import SNIFF_BYTES, sniff
from app.domain.task_key import TaskKey


class IncomingFile(Protocol):
    """A file on its way in. Nothing is read from the client before ``prepare``, and the
    name is only known once it has been."""

    @property
    def name(self) -> str | None: ...

    async def prepare(self) -> None: ...

    def chunks(self) -> AsyncIterator[bytes]: ...


class AttachFileScope(Protocol):
    """One unit of work, and what the request runs under.

    The storage, the limit and the clock belong to the request, not to the transaction:
    they are read from a scope and used while none is open, which is the point here.
    """

    @property
    def tasks(self) -> TaskRepository: ...

    @property
    def attachments(self) -> AttachmentRepository: ...

    @property
    def activity(self) -> ActivityRecorder: ...

    @property
    def file_storage(self) -> FileStorage: ...

    @property
    def max_file_bytes(self) -> int: ...

    @property
    def clock(self) -> Clock: ...


UnitOfWork = Callable[[], AbstractAsyncContextManager[AttachFileScope]]


class AttachFile:
    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def execute(
        self, reference: uuid.UUID | TaskKey, *, file: IncomingFile, created_by: uuid.UUID
    ) -> Attachment:
        """Raises ``TaskNotFound``. The reference is resolved here, not by the caller: the
        key lookup is a read like any other and belongs in the first unit of work."""
        async with self._unit_of_work() as work:
            task_id = (await GetTask(work.tasks).execute(reference)).id
            storage, max_bytes = work.file_storage, work.max_file_bytes
        await file.prepare()
        chunks = file.chunks()
        head = bytearray()
        remainder = b""
        size = 0
        async for chunk in chunks:
            size += len(chunk)
            if size > max_bytes:
                raise FileTooLargeError(max_bytes)
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
                if size > max_bytes:
                    raise FileTooLargeError(max_bytes)
                yield chunk

        async with files_following_the_transaction(storage) as files:
            stored = await storage.save(uuid.uuid4().hex, bounded())
            files.written(stored.key)
            async with self._unit_of_work() as work:
                # Only lock after upload: a slow sender must not hold a task row hostage.
                task = await work.tasks.get_for_update(task_id)
                if task is None:
                    raise TaskNotFound(reference)
                now = work.clock()
                attached = Attachment.file(
                    attachment_id=uuid.uuid4(),
                    task_id=task_id,
                    file_name=file.name,
                    file_type=file_type,
                    storage_key=stored.key,
                    size_bytes=stored.size_bytes,
                    created_by=created_by,
                    now=now,
                )
                await work.attachments.add(attached)
                task.touch(now=now)
                await work.tasks.update(task)
                await work.activity.record(
                    ActivityEntry.log(
                        entry_id=uuid.uuid4(),
                        task_id=task_id,
                        actor_id=created_by,
                        text=activity_log.attachment_added(attached.name),
                        now=now,
                    )
                )
            return attached
