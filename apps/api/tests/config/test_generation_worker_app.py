"""A generation job runs on the process's own Celery application, not a new one.

``Celery(...)`` makes itself ``current_app``, so a job that composed a second application
would silently rebind the worker process to an app that was never started.
"""

from uuid import uuid4

import pytest
from celery import current_app

from app.bootstrap import build_worker, load_settings
from app.infrastructure.jobs.step_generations import JOB_NAME


def test_sequential_jobs_keep_the_worker_application_current(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    celery_app = build_worker(load_settings())
    celery_app.set_current()
    job = celery_app.tasks[JOB_NAME]

    # Services are down, so each run composes a container, fails privately and closes it.
    for _ in range(2):
        assert job(task_id=str(uuid4())) == {"titles": [], "error": "worker_failed"}
        assert current_app._get_current_object() is celery_app

    assert celery_app.tasks[JOB_NAME] is job
