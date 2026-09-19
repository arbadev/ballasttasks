"""Attaching, reading and removing a FILE, against the in-memory fakes: what is accepted is
decided from the bytes, the size limit is enforced while the stream is read, and nothing a
refused or failed upload wrote is left behind."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

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
from app.application.use_cases.attach_file import AttachFile
from app.application.use_cases.delete_task import DeleteTask
from app.application.use_cases.open_attachment_content import OpenAttachmentContent
from app.application.use_cases.remove_attachment import RemoveAttachment
from app.domain.attachment import Attachment, AttachmentKind
from app.domain.task import Task
from tests.auth_fakes import InMemoryUserRepository
from tests.builders import a_file, a_link, a_task
from tests.fakes import (
    InMemoryAttachmentRepository,
    InMemoryProjectRepository,
    InMemoryTaskRepository,
    RecordingFileStorage,
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


@pytest.fixture
def attach_file(
    tasks: InMemoryTaskRepository,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    files: FileChanges,
) -> AttachFile:
    return AttachFile(tasks, attachments, storage, files, max_bytes=1000, clock=lambda: LATER)


class Upload:
    """A client's stream, and how much of it the server actually asked for."""

    def __init__(self, *chunks: bytes, fails_with: Exception | None = None) -> None:
        self._chunks = chunks
        self._fails_with = fails_with
        self.chunks_read = 0

    async def chunks(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.chunks_read += 1
            yield chunk
        if self._fails_with is not None:
            raise self._fails_with


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
    upload = Upload(*in_pieces(PDF, 30))

    attached = await attach_file.execute(
        task.id, file_name="../../Report Q3.pdf", chunks=upload.chunks(), created_by=CALLER
    )

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
        task.id, file_name="same.pdf", chunks=Upload(PDF).chunks(), created_by=CALLER
    )
    second = await attach_file.execute(
        task.id, file_name="same.pdf", chunks=Upload(PDF).chunks(), created_by=CALLER
    )

    assert first.storage_key != second.storage_key
    assert len(storage.stored_keys()) == 2


async def test_the_type_comes_from_the_bytes_whatever_the_name_claims(
    attach_file: AttachFile, task: Task
) -> None:
    attached = await attach_file.execute(
        task.id, file_name="report.pdf", chunks=Upload(PNG).chunks(), created_by=CALLER
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
        task.id, file_name="a.png", chunks=Upload(*in_pieces(PNG, 1)).chunks(), created_by=CALLER
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
            task.id, file_name="report.pdf", chunks=Upload(data).chunks(), created_by=CALLER
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
            task.id, file_name="empty.pdf", chunks=Upload(*chunks).chunks(), created_by=CALLER
        )

    assert storage.keys_ever_written == []
    assert attachments.all() == []


async def test_a_file_of_exactly_the_limit_is_accepted(attach_file: AttachFile, task: Task) -> None:
    exactly = PDF + b"z" * 900

    attached = await attach_file.execute(
        task.id,
        file_name="big.pdf",
        chunks=Upload(*in_pieces(exactly, 64)).chunks(),
        created_by=CALLER,
    )

    assert attached.size_bytes == 1000


async def test_a_file_over_the_limit_is_refused_while_it_streams_and_leaves_nothing_behind(
    attach_file: AttachFile,
    tasks: InMemoryTaskRepository,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    files: FileChanges,
    task: Task,
) -> None:
    too_big = PDF + b"z" * 100_000
    upload = Upload(*in_pieces(too_big, 100))

    with pytest.raises(FileTooLargeError) as raised:
        await attach_file.execute(
            task.id, file_name="big.pdf", chunks=upload.chunks(), created_by=CALLER
        )
    await files.rolled_back()

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
            file_name="big.pdf",
            chunks=Upload(PDF + b"z" * 5000).chunks(),
            created_by=CALLER,
        )

    assert storage.stored_keys() == []


async def test_a_stream_that_breaks_half_way_leaves_nothing_behind(
    attach_file: AttachFile,
    attachments: InMemoryAttachmentRepository,
    storage: RecordingFileStorage,
    files: FileChanges,
    task: Task,
) -> None:
    upload = Upload(PDF, b"more", fails_with=ConnectionResetError("the client went away"))

    with pytest.raises(ConnectionResetError):
        await attach_file.execute(
            task.id, file_name="half.pdf", chunks=upload.chunks(), created_by=CALLER
        )
    await files.rolled_back()

    assert storage.stored_keys() == []
    assert attachments.all() == []


async def test_a_task_that_does_not_exist_is_refused_before_a_byte_is_read(
    attach_file: AttachFile, storage: RecordingFileStorage
) -> None:
    upload = Upload(PDF)
    unknown = uuid.uuid4()

    with pytest.raises(TaskNotFound) as raised:
        await attach_file.execute(
            unknown, file_name="report.pdf", chunks=upload.chunks(), created_by=CALLER
        )

    assert raised.value.task_id == unknown
    assert upload.chunks_read == 0
    assert storage.keys_ever_written == []


class FailingAttachments(InMemoryAttachmentRepository):
    async def add(self, attachment: Attachment) -> None:
        raise RuntimeError("the database went away")


async def test_a_database_failure_after_the_file_was_written_leaves_no_orphan_file(
    tasks: InMemoryTaskRepository, storage: RecordingFileStorage, files: FileChanges, task: Task
) -> None:
    attach_file = AttachFile(tasks, FailingAttachments(tasks), storage, files, max_bytes=1000)

    with pytest.raises(RuntimeError, match="database went away"):
        await attach_file.execute(
            task.id, file_name="report.pdf", chunks=Upload(PDF).chunks(), created_by=CALLER
        )
    assert len(storage.stored_keys()) == 1, "written, and known to the unit of work"
    await files.rolled_back()

    assert storage.stored_keys() == []


async def test_a_task_deleted_while_the_file_streamed_leaves_no_orphan_file(
    attach_file: AttachFile,
    tasks: InMemoryTaskRepository,
    storage: RecordingFileStorage,
    files: FileChanges,
    task: Task,
) -> None:
    async def deleted_meanwhile() -> AsyncIterator[bytes]:
        yield PDF
        await tasks.delete(task.id)

    with pytest.raises(TaskNotFound):
        await attach_file.execute(
            task.id, file_name="report.pdf", chunks=deleted_meanwhile(), created_by=CALLER
        )
    await files.rolled_back()

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
        task.id, file_name="report.pdf", chunks=Upload(PDF).chunks(), created_by=CALLER
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
        task.id, file_name="report.pdf", chunks=Upload(PDF).chunks(), created_by=CALLER
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
        task.id, file_name="report.pdf", chunks=Upload(PDF).chunks(), created_by=CALLER
    )
    kept = await attach_file.execute(
        task.id, file_name="kept.pdf", chunks=Upload(PDF).chunks(), created_by=CALLER
    )
    removing = FileChanges(storage)

    await RemoveAttachment(tasks, attachments, removing).execute(task.id, attached.id)

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
        task.id, file_name="report.pdf", chunks=Upload(PDF).chunks(), created_by=CALLER
    )
    removing = FileChanges(storage)

    await RemoveAttachment(tasks, attachments, removing).execute(task.id, attached.id)
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
        await attach_file.execute(
            task.id, file_name=name, chunks=Upload(PDF).chunks(), created_by=CALLER
        )
    await attachments.add(a_link(task.id, CREATOR))
    kept = await attach_file.execute(
        other_task.id, file_name="kept.pdf", chunks=Upload(PDF).chunks(), created_by=CALLER
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
