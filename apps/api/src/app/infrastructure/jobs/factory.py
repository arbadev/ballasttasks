from celery import Celery

from app.infrastructure.jobs.tasks import JOBS


def create_celery_app(*, broker_url: str, result_backend: str, **overrides: object) -> Celery:
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
        **overrides,
    )
    for name, job in JOBS.items():
        app.task(name=name)(job)
    return app
