"""A generation job runs on the process's own Celery application, not a new one.

``Celery(...)`` makes itself ``current_app``, so a job that composed a second application
would silently rebind the worker process to an app that was never started. The async
handles stay per job: one set per ``asyncio.run``, closed before it returns.
"""

from uuid import uuid4

import pytest
from celery import current_app
from httpx import AsyncClient

from app.bootstrap import build_worker, load_settings
from app.infrastructure.ai.fake import FakeLanguageModel
from app.infrastructure.ai.registry import AI_PROVIDERS
from app.infrastructure.config.settings import AiSettings
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


def test_a_failing_job_closes_the_handles_it_opened(minimal_env: pytest.MonkeyPatch) -> None:
    clients: list[AsyncClient] = []

    def recording(ai: AiSettings, client: AsyncClient) -> FakeLanguageModel:
        clients.append(client)
        return FakeLanguageModel(model=ai.model)

    minimal_env.setitem(AI_PROVIDERS, "recording", recording)
    minimal_env.setenv("AI__PROVIDER", "recording")
    job = build_worker(load_settings()).tasks[JOB_NAME]

    assert job(task_id=str(uuid4()))["error"] == "worker_failed"
    assert job(task_id=str(uuid4()))["error"] == "worker_failed"

    assert len(clients) == 2
    assert clients[0] is not clients[1]
    assert [client.is_closed for client in clients] == [True, True]
