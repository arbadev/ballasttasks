"""HTTP contract for the project endpoints.

Lengths and patterns are repeated here only so they show up in OpenAPI; the rules themselves
live in ``app.domain.project`` and a request that slips past these models is still rejected
there.
"""

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.application.ports.project_repository import ProjectOverview
from app.application.use_cases.update_project import ProjectChanges
from app.domain.project import PROJECT_COLOR_MAX_LENGTH, PROJECT_NAME_MAX_LENGTH
from app.domain.task_key import KEY_PREFIX_MAX_LENGTH, KEY_PREFIX_MIN_LENGTH

# [^\x00]: PostgreSQL text cannot hold NUL.
ProjectName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=PROJECT_NAME_MAX_LENGTH,
        pattern=r"^[^\x00]*$",
    ),
]
ProjectColor = Annotated[
    str,
    Field(
        pattern=rf"^[a-z0-9-]{{1,{PROJECT_COLOR_MAX_LENGTH}}}$",
        description="A design token name such as `acc`; how it is drawn is the client's business.",
        examples=["acc"],
    ),
]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName = Field(examples=["Ballast Tasks"])
    key: str = Field(
        pattern=rf"^[A-Z]{{{KEY_PREFIX_MIN_LENGTH},{KEY_PREFIX_MAX_LENGTH}}}$",
        description=(
            "The prefix of the project's task keys (`BT` gives `BT-01`, `BT-02`, ...): 2 to 5 "
            "upper-case letters, unique, and fixed once the project exists."
        ),
        examples=["BT"],
    )
    color: ProjectColor | None = None


class ProjectUpdate(BaseModel):
    """Partial update: an absent field is left alone, ``null`` clears the colour.

    There is no ``key``: every task the project has created carries it.
    """

    model_config = ConfigDict(extra="forbid")

    name: ProjectName | SkipJsonSchema[None] = None
    color: ProjectColor | None = None

    @model_validator(mode="after")
    def _name_cannot_be_null(self) -> Self:
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self

    def to_changes(self) -> ProjectChanges:
        return ProjectChanges(**{name: getattr(self, name) for name in self.model_fields_set})


class ProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    key: str
    color: str | None
    open_tasks: int = Field(description="How many of the project's tasks are not `done`.")
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, overview: ProjectOverview) -> Self:
        project = overview.project
        return cls(
            id=project.id,
            name=project.name,
            key=project.key,
            color=project.color,
            open_tasks=overview.open_tasks,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class ProjectListResponse(BaseModel):
    """An envelope, like the task list; projects are few, so there are no pages."""

    items: list[ProjectResponse]
