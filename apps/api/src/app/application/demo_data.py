"""Ballast Tasks v2 demo: the API-supported fields of the web's design fixture.

Descriptions are historical sample task copy, not promises of implemented features.
This seed covers task metadata and the required creation events, not historical steps,
comments, status-change history or attachments.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.project import DEFAULT_PROJECT_ID
from app.domain.task import Task, TaskPriority, TaskStatus

# Intentionally public, local-only credentials. Never use on a deployed database.
DEMO_PASSWORD = "ballast-local-demo-only"  # noqa: S105


def demo_id(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"ballasttasks:demo:v2:{name}")


# Assistant is visible in the people directory but has no password sign-in.
DEMO_PEOPLE = (
    ("ab", "demo@ballast.example", "Andres Barradas", "owner"),
    ("lm", "lucia@ballast.example", "Lucía Marín", "backend"),
    ("tr", "tomas@ballast.example", "Tomás Rey", "frontend"),
    ("ai", "assistant@ballast.example", "Assistant", "system"),
)


@dataclass(frozen=True, slots=True)
class DemoTask:
    name: str
    title: str
    status: str
    project: str
    creator: str
    assignee: str | None
    due: int | None
    priority: int
    importance: int
    created: float
    updated: float
    description: str | None

    @property
    def project_id(self) -> uuid.UUID:
        return DEFAULT_PROJECT_ID if self.project == "inbox" else demo_id("ballast")

    def task(self, anchor: datetime, key: str) -> Task:
        updated = anchor - timedelta(days=self.updated)
        return Task(
            id=demo_id(self.name),
            title=self.title,
            description=self.description,
            status=TaskStatus(self.status),
            due_date=None if self.due is None else anchor.date() + timedelta(days=self.due),
            created_by=demo_id(self.creator),
            assignee_id=None if self.assignee is None else demo_id(self.assignee),
            created_at=anchor - timedelta(days=self.created),
            updated_at=updated,
            completed_at=updated if self.status == "done" else None,
            project_id=self.project_id,
            key=key,
            priority=TaskPriority.from_rank(self.priority),
            importance=self.importance,
        )


DEMO_TASKS = (
    DemoTask(
        name="t1",
        title="Task CRUD endpoints with pagination and filters",
        status="in_progress",
        project="ballast",
        creator="ab",
        assignee="ab",
        due=3,
        priority=0,
        importance=95,
        created=4,
        updated=0.8,
        description=(
            "FastAPI routes under /tasks. Filter by status and due date, paginate with "
            "limit/offset. The Pydantic models own the contract — run npm run gen:api after every "
            "change."
        ),
    ),
    DemoTask(
        name="t2",
        title="Next.js task list and board",
        status="in_progress",
        project="ballast",
        creator="ab",
        assignee="ab",
        due=7,
        priority=0,
        importance=85,
        created=3,
        updated=1,
        description=(
            "List and Kanban views over the same query. Components read TaskService from "
            "providers.tsx; nothing outside client.ts calls fetch."
        ),
    ),
    DemoTask(
        name="t3",
        title="Generate-steps job: Celery worker + LanguageModel port",
        status="in_progress",
        project="ballast",
        creator="tr",
        assignee="tr",
        due=5,
        priority=1,
        importance=70,
        created=2,
        updated=1,
        description=(
            "POST /tasks/{id}/steps:generate enqueues a job; the worker calls "
            "LanguageModel.generate and stores proposed steps. The UI polls until the job settles."
        ),
    ),
    DemoTask(
        name="t4",
        title="JWT authentication",
        status="todo",
        project="ballast",
        creator="ab",
        assignee=None,
        due=4,
        priority=0,
        importance=90,
        created=4,
        updated=4,
        description=(
            "Register and login, access + refresh tokens, and a current_user dependency on every "
            "/tasks route. The panel will ask about expiry and where the token lives in the "
            "browser."
        ),
    ),
    DemoTask(
        name="t5",
        title="Write PRD.md: overview, user stories, scope",
        status="todo",
        project="ballast",
        creator="ab",
        assignee="ab",
        due=-2,
        priority=1,
        importance=75,
        created=6,
        updated=3,
        description=(
            "docs/PRD.md is headings only. Fill overview, user stories and in-scope / non-goals "
            "before the CRUD slice lands, so the demo story matches the code."
        ),
    ),
    DemoTask(
        name="t6",
        title="Seed data and demo credentials",
        status="todo",
        project="ballast",
        creator="lm",
        assignee="lm",
        due=8,
        priority=1,
        importance=70,
        created=3,
        updated=3,
        description=(
            "Demo credentials and a dozen tasks across every status, so the panel sees a populated "
            "board on first run."
        ),
    ),
    DemoTask(
        name="t7",
        title="Rate limiting on the API",
        status="todo",
        project="ballast",
        creator="ab",
        assignee=None,
        due=None,
        priority=2,
        importance=55,
        created=3,
        updated=3,
        description=(
            "Behind a RateLimiter port, so the Redis token bucket is swappable for an in-memory "
            "fake in tests."
        ),
    ),
    DemoTask(
        name="t8",
        title="GenAI write-up: prompt, validation, corrections",
        status="todo",
        project="ballast",
        creator="ab",
        assignee="ab",
        due=10,
        priority=1,
        importance=75,
        created=2,
        updated=2,
        description=(
            "docs/ai-usage.md: the scaffold prompt, a representative sample of the output, how it "
            "was validated and what was corrected."
        ),
    ),
    DemoTask(
        name="t9",
        title="Presentation and code-review walkthrough",
        status="todo",
        project="ballast",
        creator="ab",
        assignee="ab",
        due=13,
        priority=1,
        importance=80,
        created=2,
        updated=2,
        description=(
            "Twelve minutes: user story, architecture, live demo, GenAI usage. Then the code "
            "review — have bootstrap.py, the ports and TaskService ready to open."
        ),
    ),
    DemoTask(
        name="t10",
        title="Unit tests at 80% coverage or more",
        status="testing",
        project="ballast",
        creator="lm",
        assignee="lm",
        due=4,
        priority=1,
        importance=65,
        created=5,
        updated=0.5,
        description=(
            "pytest --cov on the API, vitest --coverage on the web. Contract suites parametrised "
            "over every adapter of a port."
        ),
    ),
    DemoTask(
        name="t11",
        title="Docker compose: five services from .env.example",
        status="testing",
        project="ballast",
        creator="tr",
        assignee="tr",
        due=1,
        priority=2,
        importance=50,
        created=5,
        updated=1,
        description="cp .env.example .env && docker compose up --build must be the whole setup.",
    ),
    DemoTask(
        name="t12",
        title="Monorepo foundation and health endpoints",
        status="done",
        project="ballast",
        creator="ab",
        assignee="ab",
        due=-6,
        priority=0,
        importance=90,
        created=12,
        updated=6,
        description=None,
    ),
    DemoTask(
        name="t13",
        title="ADR 0002: ports and adapters",
        status="done",
        project="ballast",
        creator="ab",
        assignee="ab",
        due=-8,
        priority=2,
        importance=60,
        created=11,
        updated=8,
        description=None,
    ),
    DemoTask(
        name="t14",
        title="Pre-commit: ruff, mypy, import-linter",
        status="done",
        project="ballast",
        creator="tr",
        assignee="tr",
        due=-7,
        priority=3,
        importance=40,
        created=10,
        updated=7,
        description=None,
    ),
    DemoTask(
        name="t15",
        title="Review Vectal task detail for assistant patterns",
        status="todo",
        project="inbox",
        creator="ab",
        assignee="ab",
        due=None,
        priority=3,
        importance=30,
        created=1,
        updated=1,
        description=None,
    ),
    DemoTask(
        name="t16",
        title="Confirm the panel slot with the recruiter",
        status="todo",
        project="inbox",
        creator="ab",
        assignee="ab",
        due=0,
        priority=1,
        importance=70,
        created=1,
        updated=1,
        description=None,
    ),
)
