"""Celery results plus a small expiring association in the same Redis backend.

Celery's PENDING alone also means 'unknown'. The reservation distinguishes these and
survives FAILURE/worker loss, whose result does not contain application arguments.
No task text or provider exception is stored in the reservation.
"""

import json
from datetime import datetime, timedelta
from typing import get_args
from uuid import UUID, uuid4

from celery import Celery

from app.application.clock import Clock, utc_now
from app.application.ports.step_generation_jobs import GenerationJobsUnavailable
from app.application.step_generation import (
    GENERATION_DEADLINE_SECONDS,
    GENERATION_RETENTION_SECONDS,
    TASK_DELETED,
    Generation,
    GenerationError,
)
from app.application.use_cases.generate_step_titles import valid_titles

JOB_NAME = "generate_step_titles"
ERRORS: frozenset[GenerationError] = frozenset(get_args(GenerationError))


class CeleryStepGenerationJobs:
    def __init__(self, app: Celery, *, clock: Clock = utc_now) -> None:
        self._app = app
        self._clock = clock

    @staticmethod
    def key(job_id: UUID) -> str:
        return f"ballasttasks:step-generation:{job_id}"

    def enqueue(self, task_id: UUID) -> Generation:
        job_id = uuid4()
        now = self._clock()
        try:
            self._app.backend.client.set(
                self.key(job_id),
                json.dumps({"task_id": str(task_id), "created_at": now.isoformat()}),
                ex=GENERATION_RETENTION_SECONDS,
            )
            self._app.tasks[JOB_NAME].apply_async(
                task_id=str(job_id),
                kwargs={"task_id": str(task_id)},
                expires=now + timedelta(seconds=GENERATION_DEADLINE_SECONDS),
                retry=False,
            )
        except Exception:
            # A publish with an ambiguous acknowledgement may still run; no handle is
            # returned, and its reservation expires. Never echo transport credentials.
            raise GenerationJobsUnavailable from None
        return Generation(job_id, task_id, "pending")

    def get(self, task_id: UUID, job_id: UUID) -> Generation | None:
        try:
            raw = self._app.backend.client.get(self.key(job_id))
            if raw is None:
                return None
            reservation = json.loads(raw)
            if reservation["task_id"] != str(task_id):
                return None
            created = datetime.fromisoformat(reservation["created_at"])
            if (self._clock() - created).total_seconds() >= GENERATION_RETENTION_SECONDS:
                return None
            meta = self._app.backend.get_task_meta(str(job_id), cache=False)
            state = meta["status"]
            deadline = created + timedelta(seconds=GENERATION_DEADLINE_SECONDS)
            completed = meta.get("date_done")
            finished = datetime.fromisoformat(completed) if completed else None
            if (finished is not None and finished > deadline) or (
                finished is None and self._clock() >= deadline
            ):
                return Generation(job_id, task_id, "failure", error="timeout")
            if state == "SUCCESS":
                result = meta["result"]
                if not isinstance(result, dict):
                    return Generation(job_id, task_id, "failure", error="worker_failed")
                error = result.get("error")
                if error == TASK_DELETED:
                    # The task went with its generation: the same 404 a later poll gets.
                    return None
                if error is not None:
                    return Generation(
                        job_id,
                        task_id,
                        "failure",
                        error=error if error in ERRORS else "worker_failed",
                    )
                # Recheck the boundary: an old or malformed worker must not serve bad titles.
                return Generation(job_id, task_id, "success", valid_titles(result["titles"]))
            if state in {"FAILURE", "REVOKED"}:
                return Generation(job_id, task_id, "failure", error="worker_failed")
            if state == "STARTED":
                return Generation(job_id, task_id, "running")
            return Generation(job_id, task_id, "pending")
        except KeyError, ValueError, TypeError, RecursionError:
            return Generation(job_id, task_id, "failure", error="worker_failed")
        except Exception:
            raise GenerationJobsUnavailable from None
