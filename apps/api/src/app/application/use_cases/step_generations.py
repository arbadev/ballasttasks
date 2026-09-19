import asyncio
from uuid import UUID

from app.application.ports.step_generation_jobs import StepGenerationJobs
from app.application.step_generation import Generation, GenerationNotFound


class StepGenerations:
    """Task existence/visibility is resolved by GetTask before either operation."""

    def __init__(self, jobs: StepGenerationJobs) -> None:
        self._jobs = jobs

    async def start(self, task_id: UUID) -> Generation:
        return await asyncio.to_thread(self._jobs.enqueue, task_id)

    async def poll(self, task_id: UUID, job_id: UUID) -> Generation:
        result = await asyncio.to_thread(self._jobs.get, task_id, job_id)
        if result is None:
            raise GenerationNotFound
        return result
