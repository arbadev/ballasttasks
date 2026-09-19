"""HTTP contract for the people list: what one user may see of another."""

import uuid
from typing import Self

from pydantic import BaseModel, Field

from app.domain.user import Person


class PersonResponse(BaseModel):
    """Deliberately no email address: the people list is for picking an assignee."""

    id: uuid.UUID
    full_name: str
    initials: str = Field(description="Derived from the full name, for the avatar.")
    role_label: str | None = Field(
        description="Free text the person wrote about themselves; it grants nothing."
    )

    @classmethod
    def of(cls, person: Person) -> Self:
        return cls(
            id=person.id,
            full_name=person.full_name,
            initials=person.initials,
            role_label=person.role_label,
        )


class PeopleResponse(BaseModel):
    items: list[PersonResponse]
