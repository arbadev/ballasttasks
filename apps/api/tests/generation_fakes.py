from uuid import UUID, uuid4

from app.application.ports.step_generation_jobs import GenerationJobsUnavailable
from app.application.step_generation import Generation


class InMemoryStepGenerationJobs:
    def __init__(self) -> None:
        self.results: dict[UUID, Generation] = {}
        self.error: GenerationJobsUnavailable | None = None

    def enqueue(self, task_id: UUID) -> Generation:
        if self.error:
            raise self.error
        result = Generation(uuid4(), task_id, "pending")
        self.results[result.id] = result
        return result

    def get(self, task_id: UUID, job_id: UUID) -> Generation | None:
        if self.error:
            raise self.error
        result = self.results.get(job_id)
        return result if result is not None and result.task_id == task_id else None
