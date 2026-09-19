"""A generation job runs on the process's own Celery application, not a new one.

``Celery(...)`` makes itself ``current_app``, so a job that composed a second application
would silently rebind the worker process to an app that was never started. The async
handles stay per job: one set per ``asyncio.run``, closed before it returns.
"""

import logging
from uuid import uuid4

import pytest
from celery import current_app
from httpx import AsyncClient

from app.bootstrap import build_worker, load_settings
from app.infrastructure.ai.fake import FakeLanguageModel
from app.infrastructure.ai.registry import AI_PROVIDERS
from app.infrastructure.config.settings import AiSettings, ConfigurationError
from app.infrastructure.jobs.step_generations import JOB_NAME

# What a leaking log line would print: a credential and a vendor marker, both reachable
# from an exception raised while a job composes its container.
SECRET = "sk-live-NEVER-LOG-THIS"
PROVIDER_MARKER = "acme-vendor.example.invalid"


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


def test_a_swallowed_failure_is_reported_with_a_category_and_the_task_id(
    minimal_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A broken deployment used to poll as ``worker_failed`` with nothing in any log."""
    job = build_worker(load_settings()).tasks[JOB_NAME]
    task_id = str(uuid4())

    with caplog.at_level(logging.WARNING, logger="app.bootstrap"):
        assert job(task_id=task_id)["error"] == "worker_failed"

    (record,) = [entry for entry in caplog.records if entry.name == "app.bootstrap"]
    assert record.levelno == logging.WARNING
    # The database is the one down service the job reaches; the category names it.
    assert record.getMessage() == f"Step generation job failed: task={task_id} category=database"
    assert record.exc_info is None


def test_a_failure_log_never_carries_the_cause(
    minimal_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def leaking(ai: AiSettings, client: AsyncClient) -> FakeLanguageModel:
        raise ConfigurationError(f"AI__API_KEY={SECRET} rejected by {PROVIDER_MARKER}")

    minimal_env.setitem(AI_PROVIDERS, "leaking", leaking)
    minimal_env.setenv("AI__PROVIDER", "leaking")
    job = build_worker(load_settings()).tasks[JOB_NAME]
    task_id = str(uuid4())

    with caplog.at_level(logging.DEBUG):
        assert job(task_id=task_id) == {"titles": [], "error": "worker_failed"}

    assert f"Step generation job failed: task={task_id} category=configuration" in caplog.text
    assert SECRET not in caplog.text
    assert PROVIDER_MARKER not in caplog.text
    assert "Traceback" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_an_unparsable_task_id_is_not_echoed_into_the_log(
    minimal_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    job = build_worker(load_settings()).tasks[JOB_NAME]

    with caplog.at_level(logging.WARNING, logger="app.bootstrap"):
        assert job(task_id="not-a-uuid\nWARNING forged log line")["error"] == "worker_failed"

    (record,) = [entry for entry in caplog.records if entry.name == "app.bootstrap"]
    assert record.getMessage() == (
        "Step generation job failed: task=unparsable category=unexpected"
    )
