"""Attaching, reading and removing a FILE, against the in-memory fakes: what is accepted is
decided from the bytes, the size limit is enforced while the stream is read, nothing a
refused or failed upload wrote is left behind, and no unit of work is open while the client
is sending."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from app.application.clock import Clock
from app.application.errors import (
    AttachmentContentMissing,
    AttachmentHasNoContent,
    AttachmentNotFound,
    EmptyFileError,
    FileTooLargeError,
    TaskNotFound,
    UnsupportedFileTypeError,
)
from app.application.file_changes import FileChanges
from app.application.ports.attachment_repository import AttachmentRepository
from app.application.ports.file_storage import StoredFile
from app.application.use_cases.attach_file import AttachFile, AttachFileScope
from app.application.use_cases.delete_task import DeleteTask
from app.application.use_cases.open_attachment_content import OpenAttachmentContent
from app.application.use_cases.remove_attachment import RemoveAttachment
from app.domain.attachment import Attachment, AttachmentKind
from app.domain.task import Task
from tests.activity_fakes import InMemoryActivityLog
from tests.auth_fakes import InMemoryUserRepository
from tests.builders import a_file, a_link, a_task
from tests.fakes import (
    InMemoryAttachmentRepository,
    InMemoryProjectRepository,
    InMemoryTaskRepository,
    RecordingFileStorage,
    UploadedFile,
)

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
CREATOR = uuid.uuid4()
CALLER = uuid.uuid4()
PDF = b"%PDF-1.7\n" + b"x" * 91  # 100 bytes
PNG = b"\x89PNG\r\n\x1a\n" + b"y" * 92


@pytest.fixture
def tasks() -> InMemoryTaskRepository:
    return InMemoryTaskRepository(InMemoryUserRepository(), InMemoryProjectRepository())


@pytest.fixture
def attachments(tasks: InMemoryTaskRepository) -> InMemoryAttachmentRepository:
    return InMemoryAttachmentRepository(tasks)


@pytest.fixture
def storage() -> RecordingFileStorage:
    return RecordingFileStorage()


@pytest.fixture
def files(storage: RecordingFileStorage) -> FileChanges:
    return FileChanges(storage)


@pytest.fixture
async def task(tasks: InMemoryTaskRepository) -> Task:
    task = a_task(CREATOR, now=NOW)
    await tasks.add(task)
    return task


class Scopes:
    """Stands in for ``Container.request_scope``: the same fakes in every unit of work, and
    a record of the units that were opened and how each of them ended."""

    def __init__(
        self,
        tasks: InMemoryTaskRepository,
        attachments: AttachmentRepository,
        storage: RecordingFileStorage,
        *,
        max_bytes: int = 1000,
    ) -> None:
        self.tasks = tasks
        self.attachments = attachments
        self.activity = InMemoryActivityLog(tasks)
        self.file_storage = storage
        self.max_file_bytes = max_bytes
        self.clock: Clock = lambda: LATER
        self.events: list[str] = []

    @property
    def open_units(self) -> int:
        """How many units of work are open right now: what a slow upload must not hold."""
        return (
            self.events.count("begin") - self.events.count("commit") - self.events.count("rollback")
        )

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AttachFileScope]:
        self.events.append("begin")
        try:
            yield self
        except BaseException:
            self.events.append("rollback")
            raise
        self.events.append("commit")


async def test_upload_records_the_sanitised_name_in_the_metadata_transaction(
    tasks: InMemoryTaskRepository,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    task: Task,
) -> None:
    scopes = Scopes(tasks, attachments, storage)
    attached = await AttachFile(scopes).execute(
        task.id, file=UploadedFile(PDF, name="../../report.pdf"), created_by=CALLER
    )
    (entry,) = scopes.activity.entries
    assert (entry.text, entry.actor_id, entry.task_id, entry.created_at) == (
        "Attached report.pdf",
        CALLER,
        task.id,
        attached.created_at,
    )


class WatchingStorage(RecordingFileStorage):
    """Records how many units of work were open each time it was given, or asked for, a byte."""

    def __init__(self) -> None:
        super().__init__()
        self.units_open_while_storing: list[int] = []
        self._scopes: Scopes | None = None

    def watch(self, scopes: Scopes) -> None:
        self._scopes = scopes

    def _note(self) -> None:
        assert self._scopes is not None
        self.units_open_while_storing.append(self._scopes.open_units)

    async def save(self, key: str, chunks: AsyncIterator[bytes]) -> StoredFile:
        self._note()

        async def watched() -> AsyncIterator[bytes]:
            async for chunk in chunks:
                self._note()
                yield chunk

        return await super().save(key, watched())


def attach_file_of(scopes: Scopes) -> AttachFile:
    return AttachFile(scopes)


@pytest.fixture
def scopes(
    tasks: InMemoryTaskRepository,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
) -> Scopes:
    return Scopes(tasks, attachments, storage)


@pytest.fixture
def attach_file(scopes: Scopes) -> AttachFile:
    return attach_file_of(scopes)


def in_pieces(data: bytes, size: int) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


async def content_of(storage: RecordingFileStorage, key: str) -> bytes:
    return b"".join([chunk async for chunk in await storage.open(key)])


async def test_a_pdf_is_stored_under_a_key_of_the_servers_and_attached_for_the_caller(
    attach_file: AttachFile,
    tasks: InMemoryTaskRepository,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    task: Task,
) -> None:
    upload = UploadedFile(*in_pieces(PDF, 30), name="../../Report Q3.pdf")

    attached = await attach_file.execute(task.id, file=upload, created_by=CALLER)

    assert attached == await attachments.get(attached.id)
    assert (attached.kind, attached.content_type, attached.size_bytes, attached.name) == (
        AttachmentKind.PDF,
        "application/pdf",
        100,
        "Report Q3.pdf",
    )
    assert (attached.task_id, attached.created_by, attached.created_at) == (task.id, CALLER, LATER)
    assert attached.storage_key is not None
    assert storage.stored_keys() == [attached.storage_key]
    assert "Report" not in attached.storage_key, "the key owes nothing to the client's name"
    assert await content_of(storage, attached.storage_key) == PDF
    touched = await tasks.get(task.id)
    assert touched is not None
    assert touched.updated_at == LATER


async def test_two_uploads_of_the_same_name_never_share_a_key(
    attach_file: AttachFile, storage: RecordingFileStorage, task: Task
) -> None:
    first = await attach_file.execute(
        task.id, file=UploadedFile(PDF, name="same.pdf"), created_by=CALLER
    )
    second = await attach_file.execute(
        task.id, file=UploadedFile(PDF, name="same.pdf"), created_by=CALLER
    )

    assert first.storage_key != second.storage_key
    assert len(storage.stored_keys()) == 2


async def test_the_type_comes_from_the_bytes_whatever_the_name_claims(
    attach_file: AttachFile, task: Task
) -> None:
    attached = await attach_file.execute(
        task.id, file=UploadedFile(PNG, name="report.pdf"), created_by=CALLER
    )

    assert (attached.kind, attached.content_type, attached.name) == (
        AttachmentKind.IMAGE,
        "image/png",
        "report.pdf.png",
    )


async def test_the_type_is_recognised_even_when_the_first_bytes_arrive_one_at_a_time(
    attach_file: AttachFile, storage: RecordingFileStorage, task: Task
) -> None:
    attached = await attach_file.execute(
        task.id, file=UploadedFile(*in_pieces(PNG, 1), name="a.png"), created_by=CALLER
    )

    assert attached.content_type == "image/png"
    assert attached.storage_key is not None
    assert await content_of(storage, attached.storage_key) == PNG


@pytest.mark.parametrize(
    "data",
    [
        b"<html><script>alert(1)</script></html>",
        b"MZ\x90\x00 this is a program",
        b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>",
        b"%PD",
        b" %PDF-1.7 with a leading space",
    ],
)
async def test_bytes_that_are_neither_a_pdf_nor_an_image_are_refused_before_anything_is_written(
    attach_file: AttachFile,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    task: Task,
    data: bytes,
) -> None:
    with pytest.raises(UnsupportedFileTypeError):
        await attach_file.execute(
            task.id, file=UploadedFile(data, name="report.pdf"), created_by=CALLER
        )

    assert storage.stored_keys() == []
    assert storage.keys_ever_written == []
    assert attachments.all() == []


@pytest.mark.parametrize("chunks", [(), (b"",), (b"", b"", b"")])
async def test_an_empty_file_is_refused(
    attach_file: AttachFile,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    task: Task,
    chunks: tuple[bytes, ...],
) -> None:
    with pytest.raises(EmptyFileError):
        await attach_file.execute(
            task.id, file=UploadedFile(*chunks, name="empty.pdf"), created_by=CALLER
        )

    assert storage.keys_ever_written == []
    assert attachments.all() == []


async def test_a_file_of_exactly_the_limit_is_accepted(attach_file: AttachFile, task: Task) -> None:
    exactly = PDF + b"z" * 900

    attached = await attach_file.execute(
        task.id,
        file=UploadedFile(*in_pieces(exactly, 64), name="big.pdf"),
        created_by=CALLER,
    )

    assert attached.size_bytes == 1000


async def test_a_file_over_the_limit_is_refused_while_it_streams_and_leaves_nothing_behind(
    attach_file: AttachFile,
    tasks: InMemoryTaskRepository,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    task: Task,
) -> None:
    too_big = PDF + b"z" * 100_000
    upload = UploadedFile(*in_pieces(too_big, 100), name="big.pdf")

    with pytest.raises(FileTooLargeError) as raised:
        await attach_file.execute(task.id, file=upload, created_by=CALLER)

    assert raised.value.max_bytes == 1000
    # 1000 bytes fit in ten chunks; the eleventh proves the file is too large and is the last
    # one the server asks for, out of a thousand.
    assert upload.chunks_read == 11
    assert storage.stored_keys() == []
    assert attachments.all() == []
    assert await tasks.get(task.id) == task


async def test_a_first_chunk_that_is_already_over_the_limit_is_refused(
    attach_file: AttachFile, storage: RecordingFileStorage, task: Task
) -> None:
    with pytest.raises(FileTooLargeError):
        await attach_file.execute(
            task.id,
            file=UploadedFile(PDF + b"z" * 5000, name="big.pdf"),
            created_by=CALLER,
        )

    assert storage.stored_keys() == []


async def test_a_stream_that_breaks_half_way_leaves_nothing_behind(
    attach_file: AttachFile,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    task: Task,
) -> None:
    upload = UploadedFile(
        PDF, b"more", name="half.pdf", fails_with=ConnectionResetError("the client went away")
    )

    with pytest.raises(ConnectionResetError):
        await attach_file.execute(task.id, file=upload, created_by=CALLER)

    assert storage.stored_keys() == []
    assert attachments.all() == []


async def test_a_task_that_does_not_exist_is_refused_before_a_byte_is_read(
    attach_file: AttachFile, storage: RecordingFileStorage
) -> None:
    upload = UploadedFile(PDF, name="report.pdf")
    unknown = uuid.uuid4()

    with pytest.raises(TaskNotFound) as raised:
        await attach_file.execute(unknown, file=upload, created_by=CALLER)

    assert raised.value.task_id == unknown
    assert upload.chunks_read == 0
    assert storage.keys_ever_written == []


async def test_no_unit_of_work_is_open_while_the_client_is_sending(
    tasks: InMemoryTaskRepository, attachments: InMemoryAttachmentRepository, task: Task
) -> None:
    """The point of the two units of work: a slow sender holds no database connection.

    A file arrives in many chunks, and at every one of them, as at the moment the storage
    is handed the stream, no unit of work may be open.
    """
    storage = WatchingStorage()
    scopes = Scopes(tasks, attachments, storage)
    storage.watch(scopes)

    attached = await attach_file_of(scopes).execute(
        task.id, file=UploadedFile(*in_pieces(PDF, 10), name="report.pdf"), created_by=CALLER
    )

    assert storage.units_open_while_storing == [0] * 11, "once for the save, once per chunk"
    assert scopes.events == ["begin", "commit", "begin", "commit"], "one to check, one to write"
    assert await attachments.get(attached.id) == attached


class FailingAttachments(InMemoryAttachmentRepository):
    async def add(self, attachment: Attachment) -> None:
        raise RuntimeError("the database went away")


async def test_a_database_failure_after_the_file_was_written_leaves_no_orphan_file(
    tasks: InMemoryTaskRepository, storage: RecordingFileStorage, task: Task
) -> None:
    scopes = Scopes(tasks, FailingAttachments(tasks), storage)
    attach_file = AttachFile(scopes)

    with pytest.raises(RuntimeError, match="database went away"):
        await attach_file.execute(
            task.id, file=UploadedFile(PDF, name="report.pdf"), created_by=CALLER
        )

    assert storage.keys_ever_written != [], "the file was written before the row was"
    assert storage.stored_keys() == [], "and the rolled back unit of work took it away again"
    assert scopes.events == ["begin", "commit", "begin", "rollback"]


async def test_a_task_deleted_while_the_file_streamed_leaves_no_orphan_file(
    attach_file: AttachFile,
    tasks: InMemoryTaskRepository,
    storage: RecordingFileStorage,
    task: Task,
) -> None:
    async def delete_the_task() -> None:
        await tasks.delete(task.id)

    with pytest.raises(TaskNotFound):
        await attach_file.execute(
            task.id,
            file=UploadedFile(PDF, name="report.pdf", after=delete_the_task),
            created_by=CALLER,
        )

    assert storage.stored_keys() == []


# --- reading a file back ---------------------------------------------------------------------


@pytest.fixture
def open_content(
    attachments: InMemoryAttachmentRepository, storage: RecordingFileStorage
) -> OpenAttachmentContent:
    return OpenAttachmentContent(attachments, storage)


async def test_the_content_of_a_file_is_streamed_back_with_what_is_known_about_it(
    attach_file: AttachFile, open_content: OpenAttachmentContent, task: Task
) -> None:
    attached = await attach_file.execute(
        task.id, file=UploadedFile(PDF, name="report.pdf"), created_by=CALLER
    )

    attachment, chunks = await open_content.execute(task.id, attached.id)

    assert attachment == attached
    assert b"".join([chunk async for chunk in chunks]) == PDF


async def test_content_is_only_reached_through_the_task_the_attachment_belongs_to(
    attach_file: AttachFile,
    open_content: OpenAttachmentContent,
    tasks: InMemoryTaskRepository,
    task: Task,
) -> None:
    other_task = a_task(CREATOR)
    await tasks.add(other_task)
    attached = await attach_file.execute(
        task.id, file=UploadedFile(PDF, name="report.pdf"), created_by=CALLER
    )

    with pytest.raises(AttachmentNotFound):
        await open_content.execute(other_task.id, attached.id)
    with pytest.raises(AttachmentNotFound):
        await open_content.execute(task.id, uuid.uuid4())


async def test_a_link_has_no_content(
    open_content: OpenAttachmentContent, attachments: InMemoryAttachmentRepository, task: Task
) -> None:
    link = a_link(task.id, CREATOR)
    await attachments.add(link)

    with pytest.raises(AttachmentHasNoContent):
        await open_content.execute(task.id, link.id)


async def test_a_file_the_storage_no_longer_has_is_reported_without_naming_where_it_was(
    open_content: OpenAttachmentContent, attachments: InMemoryAttachmentRepository, task: Task
) -> None:
    lost = a_file(task.id, CREATOR)
    await attachments.add(lost)

    with pytest.raises(AttachmentContentMissing) as raised:
        await open_content.execute(task.id, lost.id)

    assert raised.value.attachment_id == lost.id
    assert lost.storage_key is not None
    assert lost.storage_key not in str(raised.value)


# --- removing ---------------------------------------------------------------------------------


async def test_removing_a_file_deletes_the_stored_file_once_the_unit_of_work_commits(
    attach_file: AttachFile,
    tasks: InMemoryTaskRepository,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    files: FileChanges,
    task: Task,
) -> None:
    attached = await attach_file.execute(
        task.id, file=UploadedFile(PDF, name="report.pdf"), created_by=CALLER
    )
    kept = await attach_file.execute(
        task.id, file=UploadedFile(PDF, name="kept.pdf"), created_by=CALLER
    )
    removing = FileChanges(storage)

    await RemoveAttachment(tasks, attachments, removing, InMemoryActivityLog(tasks)).execute(
        task.id, attached.id, actor_id=CALLER
    )

    assert attachments.all() == [kept]
    assert len(storage.stored_keys()) == 2, "not before the commit: a rollback keeps the file"
    await removing.committed()
    assert storage.stored_keys() == [kept.storage_key]


async def test_a_removal_that_is_rolled_back_keeps_the_file(
    attach_file: AttachFile,
    tasks: InMemoryTaskRepository,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    task: Task,
) -> None:
    attached = await attach_file.execute(
        task.id, file=UploadedFile(PDF, name="report.pdf"), created_by=CALLER
    )
    removing = FileChanges(storage)

    await RemoveAttachment(tasks, attachments, removing, InMemoryActivityLog(tasks)).execute(
        task.id, attached.id, actor_id=CALLER
    )
    await removing.rolled_back()

    assert storage.stored_keys() == [attached.storage_key]


async def test_deleting_a_task_deletes_the_stored_files_of_its_attachments_and_nobody_elses(
    attach_file: AttachFile,
    tasks: InMemoryTaskRepository,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    task: Task,
) -> None:
    other_task = a_task(CREATOR)
    await tasks.add(other_task)
    for name in ("one.pdf", "two.pdf"):
        await attach_file.execute(task.id, file=UploadedFile(PDF, name=name), created_by=CALLER)
    await attachments.add(a_link(task.id, CREATOR))
    kept = await attach_file.execute(
        other_task.id, file=UploadedFile(PDF, name="kept.pdf"), created_by=CALLER
    )
    deleting = FileChanges(storage)

    await DeleteTask(tasks, attachments, deleting).execute(task.id)

    assert len(storage.stored_keys()) == 3, "not before the commit"
    await deleting.committed()
    assert storage.stored_keys() == [kept.storage_key]
    assert attachments.all() == [kept]


async def test_deleting_a_task_that_does_not_exist_removes_no_file(
    tasks: InMemoryTaskRepository,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    files: FileChanges,
) -> None:
    with pytest.raises(TaskNotFound):
        await DeleteTask(tasks, attachments, files).execute(uuid.uuid4())
