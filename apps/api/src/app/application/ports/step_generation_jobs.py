from typing import Protocol
from uuid import UUID

from app.application.step_generation import Generation


class GenerationJobsUnavailable(Exception):  # noqa: N818 (application failure convention)
    def __init__(self) -> None:
        super().__init__("Step generation is temporarily unavailable. Try again.")


class StepGenerationJobs(Protocol):
    """The only job operations this feature needs; no general orchestration API.

    Calls are synchronous I/O (application dispatches them off the event loop).
    Both raise GenerationJobsUnavailable on a broker/backend outage.
    """

    def enqueue(self, task_id: UUID) -> Generation:
        """Return a distinct pending handle, without waiting for the language model."""
        ...

    def get(self, task_id: UUID, job_id: UUID) -> Generation | None:
        """None for unknown, expired, deleted or another task's handle; never empty success.

        Retained jobs have only pending/running/success/failure states. A job that
        cannot complete within the bounded deadline is a failure, even after worker loss.
        """
        ...
