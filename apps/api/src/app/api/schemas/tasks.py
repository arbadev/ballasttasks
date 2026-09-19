"""HTTP contract for the task endpoints.

Lengths are repeated here only so they show up in OpenAPI; the rules themselves live in
``app.domain.task`` and a request that slips past these models is still rejected there.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from app.api.schemas.projects import ProjectResponse
from app.api.schemas.steps import StepResponse
from app.application.ports.task_tallies import TaskTally
from app.application.task_query import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    OPEN_STATUSES,
    SEARCH_MAX_LENGTH,
    DueFilter,
    TaskFilter,
    TaskPage,
    TaskQuery,
    TaskScope,
    TaskSignal,
    TaskSort,
)
from app.application.use_cases.summarise_tasks import TaskSummary
from app.application.use_cases.update_task import TaskChanges
from app.domain.attention import Attention, AttentionReason
from app.domain.step import Step
from app.domain.task import (
    DEFAULT_IMPORTANCE,
    DEFAULT_PRIORITY,
    DESCRIPTION_MAX_LENGTH,
    IMPORTANCE_MAX,
    IMPORTANCE_MIN,
    TITLE_MAX_LENGTH,
    Task,
    TaskPriority,
    TaskStatus,
)
from app.domain.user import CONTROL_CHARACTERS

Title = Annotated[str, Field(min_length=1, max_length=TITLE_MAX_LENGTH)]
SearchText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        max_length=SEARCH_MAX_LENGTH,
        pattern=rf"^[^{CONTROL_CHARACTERS}]*$",
    ),
]
AssigneeId = Annotated[
    uuid.UUID | None,
    Field(
        description=(
            "Id of the active user the task is assigned to; `null` leaves it unassigned. "
            "An id that is not an active user is rejected with `422`."
        )
    ),
]
Importance = Annotated[
    int,
    Field(
        ge=IMPORTANCE_MIN,
        le=IMPORTANCE_MAX,
        description="How much the task matters, 0 to 100. It feeds the urgency order.",
    ),
]
ProjectId = Annotated[
    uuid.UUID,
    Field(description="Id of an existing project. An unknown id is rejected with `422`."),
]
UpdatedAssigneeId = Annotated[
    uuid.UUID | None,
    Field(
        description=(
            "Id of the active user the task is assigned to; `null` unassigns it. Checked only "
            "when it changes the assignment: an id that is not an active user is rejected with "
            "`422`, but the id the task already has is accepted even if that user has since "
            "been deactivated."
        )
    ),
]


class TaskCreate(BaseModel):
    """``created_by`` is the authenticated user; it is never read from the body."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    due_date: date | None = None
    assignee_id: AssigneeId = None
    project_id: ProjectId | None = Field(
        default=None,
        description=(
            "Id of the project the task belongs to, which also gives the task its key. Absent "
            "or `null`: the Inbox. An unknown id is rejected with `422`."
        ),
    )
    status: TaskStatus = Field(
        default=TaskStatus.TODO,
        description="The board column the task is added to. `done` completes it at once.",
    )
    priority: TaskPriority = DEFAULT_PRIORITY
    importance: Importance = DEFAULT_IMPORTANCE


class TaskUpdate(BaseModel):
    """Partial update: a field that is absent is left alone, ``null`` clears it.

    ``title``, ``status``, ``priority``, ``importance`` and ``project_id`` cannot be cleared,
    so ``null`` is rejected for them and kept out of their JSON schema. There is no ``key``:
    a task keeps the key it was created with, also when ``project_id`` moves it elsewhere.
    """

    model_config = ConfigDict(extra="forbid")

    title: Title | SkipJsonSchema[None] = None
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    status: TaskStatus | SkipJsonSchema[None] = None
    due_date: date | None = None
    assignee_id: UpdatedAssigneeId = None
    priority: TaskPriority | SkipJsonSchema[None] = None
    importance: Importance | SkipJsonSchema[None] = None
    project_id: ProjectId | SkipJsonSchema[None] = None

    @model_validator(mode="after")
    def _required_fields_cannot_be_null(self) -> Self:
        for name in ("title", "status", "priority", "importance", "project_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    def to_changes(self) -> TaskChanges:
        return TaskChanges(**{name: getattr(self, name) for name in self.model_fields_set})


class AttentionResponse(BaseModel):
    """What about the task asks for attention today, computed by the API so a client does not
    re-implement the rules. "Today" is the current UTC date."""

    model_config = ConfigDict(from_attributes=True)

    is_overdue: bool = Field(description="Open, and its due date has passed.")
    is_due_soon: bool = Field(
        description=(
            "Open, not overdue, and due today or within the window: 2 days, 3 for `P1`, 4 for `P0`."
        )
    )
    is_p0_at_risk: bool = Field(description="Open, `P0`, and due today or within its window.")
    needs_owner: bool = Field(description="Open and assigned to nobody.")
    days_until_due: int | None = Field(
        description="Whole days until the due date, negative once it has passed; `null` undated."
    )
    urgency: float = Field(description="The score `sort=urgency` orders by, highest first.")
    reasons: list[AttentionReason] = Field(
        description="Why the task asks for attention, most severe first; empty when nothing does."
    )


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str = Field(
        description="`<PROJECT KEY>-<NN>`, given at creation and never changed.",
        examples=["BT-04"],
    )
    project_id: uuid.UUID
    title: str
    description: str | None
    status: TaskStatus
    due_date: date | None
    created_by: uuid.UUID
    assignee_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    priority: TaskPriority
    importance: int
    attention: AttentionResponse
    steps_total: int = Field(description="How many steps the task has.")
    steps_done: int = Field(description="How many of them are done: the row's `2/5`.")
    comments_count: int = Field(description="How many comments its activity holds.")

    @classmethod
    def of(cls, task: Task, attention: Attention, tally: TaskTally) -> Self:
        return cls.model_validate(_task_fields(task, attention, tally), from_attributes=True)


class TaskDetailResponse(TaskResponse):
    """One task as the detail panel reads it: the task and its steps, in order."""

    steps: list[StepResponse]

    @classmethod
    def with_steps(
        cls, task: Task, attention: Attention, tally: TaskTally, steps: Sequence[Step]
    ) -> Self:
        return cls.model_validate(
            _task_fields(task, attention, tally) | {"steps": list(steps)}, from_attributes=True
        )


_COMPUTED = {"attention", "steps_total", "steps_done", "comments_count"}


def _task_fields(task: Task, attention: Attention, tally: TaskTally) -> dict[str, object]:
    stored = {
        name: getattr(task, name) for name in TaskResponse.model_fields if name not in _COMPUTED
    }
    return stored | {
        "attention": attention,
        "steps_total": tally.steps_total,
        "steps_done": tally.steps_done,
        "comments_count": tally.comments_count,
    }


class TaskListResponse(BaseModel):
    """An envelope: ``total`` is how many tasks match the filters, whatever the page."""

    items: list[TaskResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def of(cls, page: TaskPage, query: TaskQuery, items: list[TaskResponse]) -> Self:
        return cls(items=items, total=page.total, limit=query.limit, offset=query.offset)


StatusToken = Literal["open", "all", "todo", "in_progress", "testing", "done"]


class TaskFilterParams(BaseModel):
    """The filters of ``GET /tasks`` and ``GET /tasks/summary``; unknown parameters are
    rejected rather than silently ignored. What each one means is the design's
    ``Component.filtered`` and lives in ``app.application.task_query``."""

    model_config = ConfigDict(extra="forbid")

    scope: TaskScope = Field(
        default=TaskScope.ALL,
        description="`mine`: assigned to the caller. `overdue`: open and past the due date.",
    )
    project_id: uuid.UUID | None = Field(default=None, description="Only this project's tasks.")
    status: list[StatusToken] = Field(
        default=["open"],
        description=(
            "`open` (the default): everything except `done`. `all`: every status. Or one or "
            "more statuses, by repeating the parameter. `open` and `all` stand alone."
        ),
    )
    due: DueFilter | None = Field(
        default=None,
        description=(
            "`overdue`: open and past the due date. `today`. `week`: today and the six days "
            "after it. `none`: no due date. Evaluated on the current UTC date."
        ),
    )
    due_before: date | None = Field(default=None, description="Due on or before this date.")
    due_after: date | None = Field(default=None, description="Due on or after this date.")
    priority: list[TaskPriority] | None = Field(
        default=None, description="One or more priorities, by repeating the parameter."
    )
    assignee_id: uuid.UUID | Literal["unassigned"] | None = Field(
        default=None, description="A user id, or `unassigned` for tasks nobody owns."
    )
    q: SearchText | None = Field(
        default=None,
        description="Case-insensitive text to find in the title or the description.",
    )
    signal: TaskSignal | None = Field(
        default=None, description="Only the tasks behind one chip of the Attention strip."
    )

    @field_validator("q")
    @classmethod
    def _blank_is_no_search(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @model_validator(mode="after")
    def _combinations_make_sense(self) -> Self:
        if len(self.status) > 1 and {"open", "all"} & set(self.status):
            raise ValueError("status: 'open' and 'all' cannot be combined with other values")
        if self.due_before and self.due_after and self.due_after > self.due_before:
            raise ValueError("due_after must not be later than due_before")
        return self

    def to_filter(self, viewer_id: uuid.UUID) -> TaskFilter:
        if self.status == ["all"]:
            statuses = None
        elif self.status == ["open"]:
            statuses = OPEN_STATUSES
        else:
            statuses = frozenset(TaskStatus(token) for token in self.status)
        unassigned = self.assignee_id == "unassigned"
        return TaskFilter(
            scope=self.scope,
            viewer_id=viewer_id,
            project_id=self.project_id,
            statuses=statuses,
            due=self.due,
            due_before=self.due_before,
            due_after=self.due_after,
            priorities=None if self.priority is None else frozenset(self.priority),
            assignee_id=self.assignee_id if isinstance(self.assignee_id, uuid.UUID) else None,
            unassigned=unassigned,
            search=self.q,
            signal=self.signal,
        )


class TaskListParams(TaskFilterParams):
    sort: TaskSort = Field(
        default=TaskSort.URGENCY,
        description=(
            "`urgency` (see `attention.urgency`), `importance`, `due_date` (earliest first, "
            "undated last) or `updated` (most recent first). Ties: the newer task first."
        ),
    )
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size.")
    offset: int = Field(default=0, ge=0, description="How many tasks to skip.")

    def to_query(self, viewer_id: uuid.UUID) -> TaskQuery:
        return TaskQuery(
            filter=self.to_filter(viewer_id), sort=self.sort, limit=self.limit, offset=self.offset
        )


class TaskCountsResponse(BaseModel):
    """The sidebar: open tasks in the whole workspace, whatever is filtered."""

    model_config = ConfigDict(from_attributes=True)

    all: int
    mine: int
    overdue: int


class SignalCountsResponse(BaseModel):
    """The Attention strip: how many open tasks in view raise each signal."""

    model_config = ConfigDict(from_attributes=True)

    overdue: int
    p0_at_risk: int
    due_soon: int
    needs_owner: int


class TaskSummaryResponse(BaseModel):
    counts: TaskCountsResponse
    projects: list[ProjectResponse]
    signals: SignalCountsResponse

    @classmethod
    def of(cls, summary: TaskSummary) -> Self:
        return cls(
            counts=TaskCountsResponse.model_validate(summary.counts),
            projects=[ProjectResponse.of(overview) for overview in summary.projects],
            signals=SignalCountsResponse.model_validate(summary.signals),
        )
