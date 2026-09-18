import importlib
import sys

import pytest

from tests.conftest import DOWN_REDIS_URL

MODULE = "app.infrastructure.jobs.celery_app"


def test_worker_app_is_configured_only_from_settings(minimal_env: pytest.MonkeyPatch) -> None:
    sys.modules.pop(MODULE, None)

    module = importlib.import_module(MODULE)

    assert module.celery_app.conf.broker_url == DOWN_REDIS_URL
    assert module.celery_app.conf.result_backend == DOWN_REDIS_URL
    assert "ping" in module.celery_app.tasks


def test_worker_fails_fast_without_configuration(clean_env: pytest.MonkeyPatch) -> None:
    sys.modules.pop(MODULE, None)

    with pytest.raises(ValueError, match="redis"):
        importlib.import_module(MODULE)
