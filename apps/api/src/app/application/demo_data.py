"""Ballast Tasks v2 demo: the API-supported fields of the web's design fixture.

Descriptions are historical sample task copy, not promises of implemented features.
Steps, activity and attachment metadata have no persistence contract in this slice.
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
        "t1",
        "Task CRUD endpoints with pagination and filters",
        "in_progress",
        "ballast",
        "ab",
        "ab",
        3,
        0,
        95,
        4,
        0.8,
        "FastAPI routes under /tasks. Filter by status and due date, paginate with limit/offset. "
        "The Pydantic models own the contract — run npm run gen:api after every change.",
    ),
    DemoTask(
        "t2",
        "Next.js task list and board",
        "in_progress",
        "ballast",
        "ab",
        "ab",
        7,
        0,
        85,
        3,
        1,
        "List and Kanban views over the same query. "
        "Components read TaskService from providers.tsx; nothing outside client.ts calls fetch.",
    ),
    DemoTask(
        "t3",
        "Generate-steps job: Celery worker + LanguageModel port",
        "in_progress",
        "ballast",
        "tr",
        "tr",
        5,
        1,
        70,
        2,
        1,
        "POST /tasks/{id}/steps:generate enqueues a job; the worker calls LanguageModel.generate "
        "and stores proposed steps. The UI polls until the job settles.",
    ),
    DemoTask(
        "t4",
        "JWT authentication",
        "todo",
        "ballast",
        "ab",
        None,
        4,
        0,
        90,
        4,
        4,
        "Register and login, access + refresh tokens, and a current_user dependency on every "
        "/tasks route. The panel will ask about expiry and where the token lives in the browser.",
    ),
    DemoTask(
        "t5",
        "Write PRD.md: overview, user stories, scope",
        "todo",
        "ballast",
        "ab",
        "ab",
        -2,
        1,
        75,
        6,
        3,
        "docs/PRD.md is headings only. Fill overview, user stories and in-scope / non-goals "
        "before the CRUD slice lands, so the demo story matches the code.",
    ),
    DemoTask(
        "t6",
        "Seed data and demo credentials",
        "todo",
        "ballast",
        "lm",
        "lm",
        8,
        1,
        70,
        3,
        3,
        "Demo credentials and a dozen tasks across every status, so the panel sees a "
        "populated board on first run.",
    ),
    DemoTask(
        "t7",
        "Rate limiting on the API",
        "todo",
        "ballast",
        "ab",
        None,
        None,
        2,
        55,
        3,
        3,
        "Behind a RateLimiter port, so the Redis token bucket is swappable for an "
        "in-memory fake in tests.",
    ),
    DemoTask(
        "t8",
        "GenAI write-up: prompt, validation, corrections",
        "todo",
        "ballast",
        "ab",
        "ab",
        10,
        1,
        75,
        2,
        2,
        "docs/ai-usage.md: the scaffold prompt, a representative sample of the output, "
        "how it was validated and what was corrected.",
    ),
    DemoTask(
        "t9",
        "Presentation and code-review walkthrough",
        "todo",
        "ballast",
        "ab",
        "ab",
        13,
        1,
        80,
        2,
        2,
        "Twelve minutes: user story, architecture, live demo, GenAI usage. Then the code "
        "review — have bootstrap.py, the ports and TaskService ready to open.",
    ),
    DemoTask(
        "t10",
        "Unit tests at 80% coverage or more",
        "testing",
        "ballast",
        "lm",
        "lm",
        4,
        1,
        65,
        5,
        0.5,
        "pytest --cov on the API, vitest --coverage on the web. Contract suites "
        "parametrised over every adapter of a port.",
    ),
    DemoTask(
        "t11",
        "Docker compose: five services from .env.example",
        "testing",
        "ballast",
        "tr",
        "tr",
        1,
        2,
        50,
        5,
        1,
        "cp .env.example .env && docker compose up --build must be the whole setup.",
    ),
    DemoTask(
        "t12",
        "Monorepo foundation and health endpoints",
        "done",
        "ballast",
        "ab",
        "ab",
        -6,
        0,
        90,
        12,
        6,
        None,
    ),
    DemoTask(
        "t13", "ADR 0002: ports and adapters", "done", "ballast", "ab", "ab", -8, 2, 60, 11, 8, None
    ),
    DemoTask(
        "t14",
        "Pre-commit: ruff, mypy, import-linter",
        "done",
        "ballast",
        "tr",
        "tr",
        -7,
        3,
        40,
        10,
        7,
        None,
    ),
    DemoTask(
        "t15",
        "Review Vectal task detail for assistant patterns",
        "todo",
        "inbox",
        "ab",
        "ab",
        None,
        3,
        30,
        1,
        1,
        None,
    ),
    DemoTask(
        "t16",
        "Confirm the panel slot with the recruiter",
        "todo",
        "inbox",
        "ab",
        "ab",
        0,
        1,
        70,
        1,
        1,
        None,
    ),
)
