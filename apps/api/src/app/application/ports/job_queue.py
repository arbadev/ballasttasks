from collections.abc import Mapping
from typing import Protocol


class UnknownJobError(LookupError):
    """Raised when a job name is not registered with the queue."""

    def __init__(self, job_name: str, known_jobs: list[str]) -> None:
        super().__init__(f"Unknown job {job_name!r}. Known jobs: {', '.join(known_jobs) or 'none'}")
        self.job_name = job_name
        self.known_jobs = known_jobs


class JobQueue(Protocol):
    """Hands work to a background worker."""

    def enqueue(self, job_name: str, payload: Mapping[str, object]) -> str:
        """Schedule ``job_name`` with ``payload`` and return the job id.

        Raises ``UnknownJobError`` when no such job is registered.
        """
        ...
