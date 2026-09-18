from collections.abc import Mapping

from celery import Celery

from app.application.ports.job_queue import UnknownJobError
from app.infrastructure.jobs.tasks import JOBS


class CeleryJobQueue:
    def __init__(self, celery_app: Celery) -> None:
        self._celery_app = celery_app

    def enqueue(self, job_name: str, payload: Mapping[str, object]) -> str:
        if job_name not in JOBS:
            raise UnknownJobError(job_name, sorted(JOBS))
        result = self._celery_app.tasks[job_name].apply_async(kwargs=dict(payload))
        return str(result.id)
