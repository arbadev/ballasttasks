"""Attachment changes use the existing activity port and the design's wording."""

import uuid
from datetime import UTC, datetime

import pytest

from app.application.errors import AttachmentNotFound
from app.application.file_changes import FileChanges
from app.application.use_cases.attach_link import AttachLink
from app.application.use_cases.remove_attachment import RemoveAttachment
from app.domain.activity import ActivityKind
from app.infrastructure.storage.in_memory import InMemoryFileStorage
from tests.activity_fakes import InMemoryActivityLog
from tests.auth_fakes import InMemoryUserRepository
from tests.builders import a_link, a_task
from tests.fakes import (
    InMemoryAttachmentRepository,
    InMemoryProjectRepository,
    InMemoryTaskRepository,
)

NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)


async def test_attaching_a_link_records_its_resolved_name_caller_and_time() -> None:
    creator, caller = uuid.uuid4(), uuid.uuid4()
    tasks = InMemoryTaskRepository(InMemoryUserRepository(), InMemoryProjectRepository())
    task = a_task(creator)
    await tasks.add(task)
    attachments, activity = InMemoryAttachmentRepository(tasks), InMemoryActivityLog(tasks)

    await AttachLink(tasks, attachments, activity, clock=lambda: NOW).execute(
        task.id, url="https://example.com/spec", name=None, created_by=caller
    )

    (entry,) = activity.entries
    assert (entry.task_id, entry.actor_id, entry.created_at, entry.kind, entry.text) == (
        task.id,
        caller,
        NOW,
        ActivityKind.LOG,
        "Attached example.com",
    )


async def test_removing_records_the_remover_not_the_attachment_creator_and_no_failed_attempt() -> (
    None
):
    creator, caller = uuid.uuid4(), uuid.uuid4()
    tasks = InMemoryTaskRepository(InMemoryUserRepository(), InMemoryProjectRepository())
    task = a_task(creator)
    await tasks.add(task)
    attachments, activity = InMemoryAttachmentRepository(tasks), InMemoryActivityLog(tasks)
    link = a_link(task.id, creator, name="The spec")
    await attachments.add(link)
    remove = RemoveAttachment(
        tasks, attachments, FileChanges(InMemoryFileStorage()), activity, clock=lambda: NOW
    )

    await remove.execute(task.id, link.id, actor_id=caller)
    with pytest.raises(AttachmentNotFound):
        await remove.execute(task.id, link.id, actor_id=caller)

    (entry,) = activity.entries
    assert (entry.task_id, entry.actor_id, entry.created_at, entry.text) == (
        task.id,
        caller,
        NOW,
        "Removed The spec",
    )
