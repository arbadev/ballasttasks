"""Background jobs. Plain functions: ``factory.create_celery_app`` registers them by name."""

from collections.abc import Callable, Mapping


def ping() -> str:
    return "pong"


# job name -> callable. Adding a job is a new function plus one line here.
JOBS: Mapping[str, Callable[..., object]] = {
    "ping": ping,
}
