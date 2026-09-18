"""Worker entrypoint: ``celery -A app.infrastructure.jobs.celery_app worker``.

Configured only from ``Settings`` (broker and result backend on Redis); importing this
module without a valid environment fails fast, like the API does at startup.
"""

from app.infrastructure.config.settings import Settings
from app.infrastructure.jobs.factory import create_celery_app

_settings = Settings()

celery_app = create_celery_app(
    broker_url=_settings.redis.url,
    result_backend=_settings.redis.url,
)
