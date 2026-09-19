"""Insert the design demo once, or verify it without ever repairing/overwriting data.

The caller owns one transaction. The Inbox row lock serialises concurrent seed runs;
its metadata is never changed. The demo project's creation time anchors relative dates
on reruns, so tomorrow's invocation cannot reschedule yesterday's tasks.
"""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

from app.application.clock import Clock
from app.application.demo_data import DEMO_PASSWORD, DEMO_PEOPLE, DEMO_TASKS, demo_id
from app.application.errors import EmailAlreadyRegisteredError, ProjectKeyTakenError
from app.application.ports.activity_feed import ActivityFeed
from app.application.ports.activity_recorder import ActivityRecorder
from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.project_repository import ProjectRepository
from app.application.ports.task_repository import TaskRepository
from app.application.ports.user_repository import UserRepository
from app.domain import activity_log
from app.domain.activity import ActivityEntry
from app.domain.project import DEFAULT_PROJECT_ID, Project
from app.domain.user import User


class DemoSeedConflictError(ValueError):
    """No record can be confidently reused; leave the entire database unchanged."""

    def __init__(self) -> None:
        super().__init__("Demo seed conflict: existing or edited records; nothing was changed")


def _project(anchor: datetime) -> Project:
    return Project.create(
        project_id=demo_id("ballast"), name="Ballast Tasks", key="BT", color="acc", now=anchor
    )


class SeedDemo:
    def __init__(
        self,
        users: UserRepository,
        projects: ProjectRepository,
        tasks: TaskRepository,
        passwords: PasswordHasher,
        activity: ActivityRecorder,
        activity_feed: ActivityFeed,
        *,
        clock: Clock,
    ) -> None:
        self._users, self._projects, self._tasks = users, projects, tasks
        self._passwords, self._clock = passwords, clock
        self._activity, self._activity_feed = activity, activity_feed

    async def execute(self) -> bool:
        """True when created; False for an intact rerun. Every conflict raises."""
        if await self._projects.get_for_update(DEFAULT_PROJECT_ID) is None:
            raise DemoSeedConflictError
        existing = await self._projects.get_for_update(demo_id("ballast"))
        anchor = self._clock() if existing is None else existing.created_at
        if existing is not None and existing != _project(anchor):
            raise DemoSeedConflictError
        try:
            for name, email, full_name, role in DEMO_PEOPLE:
                user = await self._users.get_by_id(demo_id(name))
                by_email = await self._users.get_by_email(email)
                expected = User(
                    id=demo_id(name),
                    email=email,
                    full_name=full_name,
                    role_label=role,
                    hashed_password=None,
                    is_active=True,
                    created_at=anchor,
                )
                if existing is None:
                    if user is not None or by_email is not None:
                        raise DemoSeedConflictError
                    hashed = (
                        None
                        if name == "ai"
                        else await asyncio.to_thread(self._passwords.hash, DEMO_PASSWORD)
                    )
                    await self._users.add(replace(expected, hashed_password=hashed))
                else:
                    if (
                        user is None
                        or by_email != user
                        or replace(user, hashed_password=None) != expected
                    ):
                        raise DemoSeedConflictError
                    if name == "ai":
                        valid = user.hashed_password is None
                    else:
                        valid = user.hashed_password is not None and await asyncio.to_thread(
                            self._passwords.verify, DEMO_PASSWORD, user.hashed_password
                        )
                    if not valid:
                        raise DemoSeedConflictError
            if existing is None:
                await self._projects.add(_project(anchor))
            for spec in DEMO_TASKS:
                task = await self._tasks.get(demo_id(spec.name))
                creation = ActivityEntry.log(
                    entry_id=demo_id(f"{spec.name}:created"),
                    task_id=demo_id(spec.name),
                    actor_id=demo_id(spec.creator),
                    text=activity_log.CREATED,
                    now=anchor - timedelta(days=spec.created),
                )
                if existing is not None:
                    if task is None or task != spec.task(anchor, task.key):
                        raise DemoSeedConflictError
                    page = await self._activity_feed.page(task.id, limit=1, offset=0)
                    if page.total != 1 or [item.entry for item in page.items] != [creation]:
                        raise DemoSeedConflictError
                else:
                    if task is not None:
                        raise DemoSeedConflictError
                    key = await self._projects.allocate_task_key(spec.project_id)
                    task = spec.task(anchor, str(key))
                    await self._tasks.add(task)
                    await self._activity.record(creation)
        except (EmailAlreadyRegisteredError, ProjectKeyTakenError) as error:
            raise DemoSeedConflictError from error
        return existing is None
