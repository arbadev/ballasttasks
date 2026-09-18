"""HTTP contract for the health endpoints.

These models become the OpenAPI components the frontend types are generated from:
change one, run ``gen:api`` and fix the frontend in the same commit.
"""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ComponentStatus(BaseModel):
    name: str
    status: Literal["ok", "failed"]


class AiInfo(BaseModel):
    provider: str
    model: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: list[ComponentStatus]
    ai: AiInfo
