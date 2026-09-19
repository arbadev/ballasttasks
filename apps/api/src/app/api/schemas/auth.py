import uuid
from datetime import datetime
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

from app.application.use_cases.update_profile import ProfileChanges
from app.domain.user import (
    CONTROL_CHARACTERS,
    FULL_NAME_MAX_LENGTH,
    MAX_EMAIL_LENGTH,
    MAX_PASSWORD_LENGTH,
    ROLE_LABEL_MAX_LENGTH,
    User,
    normalise_email,
)

NO_CONTROL_CHARACTERS = rf"^[^{CONTROL_CHARACTERS}]*$"
FullName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=FULL_NAME_MAX_LENGTH,
        pattern=NO_CONTROL_CHARACTERS,
    ),
]


class RegisterRequest(BaseModel):
    email: str = Field(max_length=MAX_EMAIL_LENGTH + 64, examples=["ada@example.com"])
    full_name: FullName = Field(examples=["Ada Lovelace"])
    password: str = Field(
        min_length=8,
        max_length=MAX_PASSWORD_LENGTH,
        pattern=NO_CONTROL_CHARACTERS,
        json_schema_extra={"writeOnly": True, "format": "password"},
    )

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return normalise_email(value)


class ProfileUpdate(BaseModel):
    """What a user may change about themselves. Partial: an absent field is left alone.

    Nothing else is accepted: not the email, not the password, not ``is_active``.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: FullName | SkipJsonSchema[None] = None
    role_label: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True,
                max_length=ROLE_LABEL_MAX_LENGTH,
                pattern=NO_CONTROL_CHARACTERS,
            ),
        ]
        | None
    ) = Field(
        default=None,
        description=(
            "Free text shown next to the name in the people list, such as `backend`. `null` "
            "or blank text clears it. It is a label: it grants and refuses nothing."
        ),
        examples=["backend"],
    )

    @model_validator(mode="after")
    def _full_name_cannot_be_null(self) -> Self:
        if "full_name" in self.model_fields_set and self.full_name is None:
            raise ValueError("full_name cannot be null")
        return self

    def to_changes(self) -> ProfileChanges:
        return ProfileChanges(**{name: getattr(self, name) for name in self.model_fields_set})


class UserResponse(BaseModel):
    """A user as the API shows it. There is deliberately no field for the password hash."""

    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    created_at: datetime
    initials: str
    role_label: str | None

    @classmethod
    def from_user(cls, user: User) -> UserResponse:
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            created_at=user.created_at,
            initials=user.initials,
            role_label=user.role_label,
        )


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  (the OAuth2 token type, not a secret)
