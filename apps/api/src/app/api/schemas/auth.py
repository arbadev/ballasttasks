import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.domain.user import MAX_EMAIL_LENGTH, User, normalise_email

FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class RegisterRequest(BaseModel):
    email: str = Field(max_length=MAX_EMAIL_LENGTH + 64, examples=["ada@example.com"])
    full_name: FullName = Field(examples=["Ada Lovelace"])
    password: str = Field(
        min_length=8, max_length=128, json_schema_extra={"writeOnly": True, "format": "password"}
    )

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return normalise_email(value)


class UserResponse(BaseModel):
    """A user as the API shows it. There is deliberately no field for the password hash."""

    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> UserResponse:
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            created_at=user.created_at,
        )


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  (the OAuth2 token type, not a secret)
