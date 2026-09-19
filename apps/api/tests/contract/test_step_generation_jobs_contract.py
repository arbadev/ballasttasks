from collections.abc import Iterator
from uuid import uuid4

import pytest

from app.application.ports.step_generation_jobs import StepGenerationJobs
from app.bootstrap import build_worker, load_settings
from app.infrastructure.jobs.step_generations import CeleryStepGenerationJobs
from tests.generation_fakes import InMemoryStepGenerationJobs


@pytest.fixture(params=["memory", pytest.param("celery", marks=pytest.mark.integration)])
def jobs(request: pytest.FixtureRequest) -> Iterator[StepGenerationJobs]:
    if request.param == "memory":
        yield InMemoryStepGenerationJobs()
    else:
        app = build_worker(load_settings())
        # No worker consumes this queue; contract assertions must observe PENDING.
        queue = f"generation-contract-{uuid4().hex}"
        app.conf.task_default_queue = queue
        adapter = CeleryStepGenerationJobs(app)
        yield adapter
        app.backend.client.delete(queue)
        app.close()


def test_enqueues_distinct_task_associated_pending_handles(jobs: StepGenerationJobs) -> None:
    task_id, other_id = uuid4(), uuid4()
    results = [jobs.enqueue(task_id), jobs.enqueue(task_id), jobs.enqueue(other_id)]
    assert len({r.id for r in results}) == 3
    for result in results:
        assert result.state == "pending"
        assert result.titles == ()
        assert result.error is None
        assert jobs.get(result.task_id, result.id) == result
    assert jobs.get(other_id, results[0].id) is None
    assert jobs.get(task_id, uuid4()) is None
