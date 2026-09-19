"""Native Redis/Celery backend states, retention, and safe transport failure mapping."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.application.clock import utc_now
from app.application.ports.step_generation_jobs import GenerationJobsUnavailable
from app.application.step_generation import GENERATION_RETENTION_SECONDS
from app.bootstrap import build_worker, load_settings
from app.infrastructure.jobs.step_generations import CeleryStepGenerationJobs

pytestmark = pytest.mark.integration


@dataclass
class Clock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


def test_native_states_unknown_retention_and_lost_worker() -> None:
    app = build_worker(load_settings())
    queue = f"generation-state-test-{uuid4().hex}"
    app.conf.task_default_queue = queue
    clock = Clock(utc_now())
    jobs = CeleryStepGenerationJobs(app, clock=clock)
    task = uuid4()
    handle = jobs.enqueue(task)
    lost = jobs.enqueue(task)
    try:
        assert app.backend.client.ttl(jobs.key(handle.id)) <= GENERATION_RETENTION_SECONDS
        assert jobs.get(task, uuid4()) is None
        assert jobs.get(uuid4(), handle.id) is None
        app.backend.store_result(str(handle.id), {"pid": 123, "hostname": "private"}, "STARTED")
        running = jobs.get(task, handle.id)
        assert running is not None
        assert running.state == "running"
        assert running.titles == ()
        app.backend.store_result(
            str(handle.id), {"titles": [" first ", "second"], "error": None}, "SUCCESS"
        )
        success = jobs.get(task, handle.id)
        assert success is not None
        assert success.state == "success"
        assert success.titles == ("first", "second")
        clock.now += timedelta(seconds=301)
        # Completed in time remains successful; a vanished worker becomes retryable failure.
        assert jobs.get(task, handle.id) == success
        timed_out = jobs.get(task, lost.id)
        assert timed_out is not None
        assert timed_out.error == "timeout"
        clock.now += timedelta(seconds=GENERATION_RETENTION_SECONDS)
        assert jobs.get(task, handle.id) is None
        assert jobs.get(task, lost.id) is None
    finally:
        for job in (handle, lost):
            app.backend.client.delete(jobs.key(job.id))
            app.backend.forget(str(job.id))
        app.backend.client.delete(queue)
        app.close()


@pytest.mark.parametrize(
    ("state", "result", "expected"),
    [
        ("FAILURE", RuntimeError("PRIVATE-PROVIDER-SECRET"), "worker_failed"),
        ("REVOKED", RuntimeError("PRIVATE-PROVIDER-SECRET"), "worker_failed"),
        ("SUCCESS", {"titles": [], "error": None}, "worker_failed"),
        ("SUCCESS", {"titles": ["\ud800"], "error": None}, "worker_failed"),
        ("SUCCESS", ["unexpected shape"], "worker_failed"),
        ("SUCCESS", {"titles": ["ok"], "error": "unknown-private-error"}, "worker_failed"),
        ("SUCCESS", {"titles": ["ok"], "error": "invalid_output"}, "invalid_output"),
    ],
)
def test_terminal_backend_failures_never_expose_exceptions(
    state: str, result: object, expected: str
) -> None:
    app = build_worker(load_settings())
    queue = f"generation-failure-test-{uuid4().hex}"
    app.conf.task_default_queue = queue
    jobs = CeleryStepGenerationJobs(app)
    handle = jobs.enqueue(uuid4())
    try:
        app.backend.store_result(str(handle.id), result, state)
        failure = jobs.get(handle.task_id, handle.id)
        assert failure is not None
        assert failure.state == "failure"
        assert failure.error == expected
        assert failure.titles == ()
        assert "PRIVATE-PROVIDER-SECRET" not in repr(failure)
        app.backend.client.delete(jobs.key(handle.id))
        assert jobs.get(handle.task_id, handle.id) is None
    finally:
        app.backend.forget(str(handle.id))
        app.backend.client.delete(queue)
        app.close()


def test_titles_of_any_script_survive_the_read_boundary() -> None:
    """A batch valid at 200 characters a title stays valid however wide its characters are.

    Non-BMP titles are the worst case: the limits count characters, so a legitimate
    success must never come back as a failure because of how the result was re-encoded.
    """
    app = build_worker(load_settings())
    queue = f"generation-unicode-test-{uuid4().hex}"
    app.conf.task_default_queue = queue
    jobs = CeleryStepGenerationJobs(app)
    titles = ["\U0001f600" * 137] * 20
    handle = jobs.enqueue(uuid4())
    try:
        app.backend.store_result(str(handle.id), {"titles": titles, "error": None}, "SUCCESS")
        drafted = jobs.get(handle.task_id, handle.id)
        assert drafted is not None
        assert drafted.state == "success"
        assert drafted.titles == tuple(titles)
    finally:
        app.backend.client.delete(jobs.key(handle.id))
        app.backend.forget(str(handle.id))
        app.backend.client.delete(queue)
        app.close()


def test_a_generation_whose_task_vanished_is_a_missing_generation() -> None:
    """The route answers 404 from None, so this is what keeps `task_deleted` off the wire,
    including a deletion that lands after the poll's own task lookup succeeded."""
    app = build_worker(load_settings())
    queue = f"generation-deleted-test-{uuid4().hex}"
    app.conf.task_default_queue = queue
    jobs = CeleryStepGenerationJobs(app)
    handle = jobs.enqueue(uuid4())
    try:
        app.backend.store_result(str(handle.id), {"titles": [], "error": "task_deleted"}, "SUCCESS")
        assert jobs.get(handle.task_id, handle.id) is None
    finally:
        app.backend.client.delete(jobs.key(handle.id))
        app.backend.forget(str(handle.id))
        app.backend.client.delete(queue)
        app.close()


def test_backend_outage_is_typed_and_private(minimal_env: pytest.MonkeyPatch) -> None:
    jobs = CeleryStepGenerationJobs(build_worker(load_settings()))
    with pytest.raises(GenerationJobsUnavailable, match="temporarily unavailable"):
        jobs.enqueue(uuid4())
    with pytest.raises(GenerationJobsUnavailable, match="temporarily unavailable"):
        jobs.get(uuid4(), uuid4())
