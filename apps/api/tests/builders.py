"""Builders for the entities most tests need: a task already has a project and a key."""

import itertools
import uuid
from datetime import UTC, datetime

from app.domain.project import DEFAULT_PROJECT_ID, Project
from app.domain.task import Task

CREATED = datetime(2026, 1, 5, 9, 0, 0, 123456, tzinfo=UTC)

_numbers = itertools.count(1)


def a_task(created_by: uuid.UUID, **overrides: object) -> Task:
    """A task in the Inbox with a key nobody else has; ``overrides`` go to ``Task.create``."""
    arguments: dict[str, object] = {
        "task_id": uuid.uuid4(),
        "title": "Write the report",
        "created_by": created_by,
        "project_id": DEFAULT_PROJECT_ID,
        "key": f"ZZ-{next(_numbers):02d}",
        "now": CREATED,
    }
    return Task.create(**(arguments | overrides))  # type: ignore[arg-type]


def a_project(**overrides: object) -> Project:
    arguments: dict[str, object] = {
        "project_id": uuid.uuid4(),
        "name": "Ballast Tasks",
        "key": "BT",
        "now": CREATED,
    }
    return Project.create(**(arguments | overrides))  # type: ignore[arg-type]
