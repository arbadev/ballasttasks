"""Drafts are results, not stored steps. Only AddSteps accepts them into a task."""

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

GenerationState = Literal["pending", "running", "success", "failure"]
# What a poll may publish. A task that no longer exists is a 404, not a failure code, so
# TASK_DELETED stays inside the worker and never reaches a response.
GenerationError = Literal["invalid_output", "provider_unavailable", "timeout", "worker_failed"]
TASK_DELETED: Final = "task_deleted"
WorkerError = Literal[GenerationError, "task_deleted"]

# Fixed resource/lifetime bounds, shared by the queue and worker.
GENERATION_RETENTION_SECONDS = 3600
GENERATION_DEADLINE_SECONDS = 300
GENERATION_MODEL_MAX_SECONDS = 240
MAX_COMPLETION_CHARACTERS = 32768


@dataclass(frozen=True, slots=True)
class GenerationOutcome:
    titles: tuple[str, ...] = ()
    error: WorkerError | None = None


@dataclass(frozen=True, slots=True)
class Generation:
    id: UUID
    task_id: UUID
    state: GenerationState
    titles: tuple[str, ...] = ()
    error: GenerationError | None = None


class GenerationNotFound(LookupError):  # noqa: N818 (matches TaskNotFound)
    def __init__(self) -> None:
        super().__init__("No retained generation for this task has that id")
