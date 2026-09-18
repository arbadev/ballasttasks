"""Contract every JobQueue adapter must honour.

Registering a new adapter = one new factory line in ``ADAPTERS``.
The default run configures the REAL ``CeleryJobQueue`` with Celery's in-memory
broker/backend and eager execution (test configuration, not a different adapter);
the ``integration`` entry runs it against the live Redis broker.
"""

from collections.abc import Callable

import pytest

from app.application.ports.job_queue import JobQueue, UnknownJobError
from app.infrastructure.config.settings import Settings
from app.infrastructure.jobs.factory import create_celery_app
from app.infrastructure.jobs.queue import CeleryJobQueue

AdapterFactory = Callable[[], JobQueue]


def celery_in_memory() -> JobQueue:
    app = create_celery_app(
        broker_url="memory://",
        result_backend="cache+memory://",
        task_always_eager=True,
    )
    return CeleryJobQueue(app)


def celery_live() -> JobQueue:
    url = Settings().redis.url
    return CeleryJobQueue(create_celery_app(broker_url=url, result_backend=url))


ADAPTERS = [
    pytest.param(celery_in_memory, id="celery-in-memory"),
    pytest.param(celery_live, id="celery-live", marks=pytest.mark.integration),
]


@pytest.mark.parametrize("factory", ADAPTERS)
def test_enqueue_of_a_known_job_returns_a_job_id(factory: AdapterFactory) -> None:
    job_id = factory().enqueue("ping", {})

    assert isinstance(job_id, str)
    assert job_id


@pytest.mark.parametrize("factory", ADAPTERS)
def test_enqueue_of_an_unknown_job_raises_a_clear_error(factory: AdapterFactory) -> None:
    with pytest.raises(UnknownJobError, match="no-such-job") as error:
        factory().enqueue("no-such-job", {})

    assert "ping" in str(error.value)  # the message lists the known jobs
