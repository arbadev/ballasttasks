"""Attaching, listing and removing, against the in-memory fakes."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.application.errors import AttachmentNotFound, TaskNotFound
from app.application.file_changes import FileChanges
from app.application.use_cases.attach_link import AttachLink
from app.application.use_cases.list_attachments import ListAttachments
from app.application.use_cases.remove_attachment import RemoveAttachment
from app.domain.attachment import AttachmentKind, InvalidAttachmentError
from app.domain.task import Task
from app.infrastructure.storage.in_memory import InMemoryFileStorage
from tests.activity_fakes import InMemoryActivityLog
from tests.auth_fakes import InMemoryUserRepository
from tests.builders import a_file, a_link, a_task
from tests.fakes import (
    InMemoryAttachmentRepository,
    InMemoryProjectRepository,
    InMemoryTaskRepository,
)

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
CREATOR = uuid.uuid4()
CALLER = uuid.uuid4()


def no_files() -> FileChanges:
    return FileChanges(InMemoryFileStorage())


@pytest.fixture
def tasks() -> InMemoryTaskRepository:
    return InMemoryTaskRepository(InMemoryUserRepository(), InMemoryProjectRepository())


@pytest.fixture
def attachments(tasks: InMemoryTaskRepository) -> InMemoryAttachmentRepository:
    return InMemoryAttachmentRepository(tasks)


@pytest.fixture
async def task(tasks: InMemoryTaskRepository) -> Task:
    task = a_task(CREATOR, now=NOW)
    await tasks.add(task)
    return task


async def test_attach_link_stores_the_link_for_the_caller_and_touches_the_task(
    tasks: InMemoryTaskRepository, attachments: InMemoryAttachmentRepository, task: Task
) -> None:
    attachment_id = uuid.uuid4()
    attach_link = AttachLink(
        tasks,
        attachments,
        InMemoryActivityLog(tasks),
        clock=lambda: LATER,
        new_id=lambda: attachment_id,
    )

    link = await attach_link.execute(
        task.id, url="https://example.com/spec", name="The spec", created_by=CALLER
    )

    assert link == await attachments.get(attachment_id)
    assert (link.kind, link.url, link.name) == (
        AttachmentKind.LINK,
        "https://example.com/spec",
        "The spec",
    )
    assert (link.task_id, link.created_by, link.created_at) == (task.id, CALLER, LATER)
    touched = await tasks.get(task.id)
    assert touched is not None
    assert (touched.updated_at, touched.created_at) == (LATER, NOW)


async def test_attach_link_to_an_unknown_task_raises_and_stores_nothing(
    tasks: InMemoryTaskRepository, attachments: InMemoryAttachmentRepository
) -> None:
    unknown = uuid.uuid4()

    with pytest.raises(TaskNotFound) as raised:
        await AttachLink(tasks, attachments, InMemoryActivityLog(tasks)).execute(
            unknown, url="https://example.com", name=None, created_by=CALLER
        )

    assert raised.value.task_id == unknown
    assert attachments.all() == []


async def test_attach_link_with_a_url_the_domain_refuses_stores_nothing_and_leaves_the_task_alone(
    tasks: InMemoryTaskRepository, attachments: InMemoryAttachmentRepository, task: Task
) -> None:
    with pytest.raises(InvalidAttachmentError):
        await AttachLink(
            tasks, attachments, InMemoryActivityLog(tasks), clock=lambda: LATER
        ).execute(task.id, url="javascript:alert(1)", name=None, created_by=CALLER)

    assert attachments.all() == []
    assert await tasks.get(task.id) == task


async def test_list_attachments_returns_a_tasks_attachments_and_counts_several_tasks(
    tasks: InMemoryTaskRepository, attachments: InMemoryAttachmentRepository, task: Task
) -> None:
    bare = a_task(CREATOR)
    await tasks.add(bare)
    first = a_file(task.id, CREATOR, created_at=NOW)
    second = a_link(task.id, CREATOR, now=LATER)
    await attachments.add(second)
    await attachments.add(first)
    list_attachments = ListAttachments(attachments)

    assert list(await list_attachments.execute(task.id)) == [first, second]
    assert await list_attachments.count([task.id, bare.id]) == {task.id: 2, bare.id: 0}


async def test_remove_attachment_removes_it_and_touches_the_task(
    tasks: InMemoryTaskRepository, attachments: InMemoryAttachmentRepository, task: Task
) -> None:
    link, kept = a_link(task.id, CREATOR), a_link(task.id, CREATOR)
    await attachments.add(link)
    await attachments.add(kept)

    await RemoveAttachment(
        tasks, attachments, no_files(), InMemoryActivityLog(tasks), clock=lambda: LATER
    ).execute(task.id, link.id, actor_id=CALLER)

    assert attachments.all() == [kept]
    touched = await tasks.get(task.id)
    assert touched is not None
    assert touched.updated_at == LATER


async def test_remove_attachment_of_an_unknown_id_raises(
    tasks: InMemoryTaskRepository, attachments: InMemoryAttachmentRepository, task: Task
) -> None:
    unknown = uuid.uuid4()

    with pytest.raises(AttachmentNotFound) as raised:
        await RemoveAttachment(tasks, attachments, no_files(), InMemoryActivityLog(tasks)).execute(
            task.id, unknown, actor_id=CALLER
        )

    assert raised.value.attachment_id == unknown


async def test_an_attachment_is_only_removed_through_the_task_it_belongs_to(
    tasks: InMemoryTaskRepository, attachments: InMemoryAttachmentRepository, task: Task
) -> None:
    other_task = a_task(CREATOR)
    await tasks.add(other_task)
    link = a_link(other_task.id, CREATOR)
    await attachments.add(link)

    with pytest.raises(AttachmentNotFound):
        await RemoveAttachment(
            tasks, attachments, no_files(), InMemoryActivityLog(tasks), clock=lambda: LATER
        ).execute(task.id, link.id, actor_id=CALLER)

    assert attachments.all() == [link]
    assert await tasks.get(task.id) == task
