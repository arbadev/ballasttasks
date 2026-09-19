"""Celery entrypoint: celery -A app.worker worker --loglevel=INFO.

Like main, this delegates all concrete choices to the composition root. The process
has one Celery application, the one built here; each job owns its async resources
and closes them before its event loop exits.
"""

from app.bootstrap import build_worker, load_settings

celery_app = build_worker(load_settings())
