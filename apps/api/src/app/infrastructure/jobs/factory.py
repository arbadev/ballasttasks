from collections.abc import Callable

from celery import Celery

from app.application.step_generation import GENERATION_MODEL_MAX_SECONDS
from app.infrastructure.jobs.step_generations import JOB_NAME
from app.infrastructure.jobs.tasks import JOBS


def create_celery_app(
    *,
    broker_url: str,
    result_backend: str,
    generate_steps: Callable[[str], dict[str, object]] | None = None,
    **overrides: object,
) -> Celery:
    """Build a Celery app with every job registered.

    ``overrides`` are extra Celery settings (tests use ``task_always_eager=True``).
    """
    app = Celery("ballasttasks", broker=broker_url, backend=result_backend)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        broker_connection_retry_on_startup=True,
        result_expires=3600,
        broker_connection_timeout=2,
        broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 2},
        redis_socket_connect_timeout=2,
        redis_socket_timeout=2,
        result_backend_always_retry=False,
        **overrides,
    )
    # shared=False: a task belongs to the app built here, never to one built later in the
    # same process, so a second app cannot inherit this app's job callables.
    for name, job in JOBS.items():
        app.task(name=name, shared=False)(job)
    if generate_steps is not None:
        app.task(
            name=JOB_NAME,
            shared=False,
            track_started=True,
            time_limit=GENERATION_MODEL_MAX_SECONDS + 10,
        )(generate_steps)
    return app
