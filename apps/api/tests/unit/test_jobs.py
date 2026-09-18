from app.infrastructure.jobs.factory import create_celery_app
from app.infrastructure.jobs.tasks import ping


def test_ping_returns_pong() -> None:
    assert ping() == "pong"


def test_ping_task_round_trip_through_celery() -> None:
    app = create_celery_app(
        broker_url="memory://", result_backend="cache+memory://", task_always_eager=True
    )

    assert app.tasks["ping"].delay().get(timeout=5) == "pong"
