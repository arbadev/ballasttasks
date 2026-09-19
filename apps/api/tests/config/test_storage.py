from pathlib import Path

import pytest
from pydantic import ValidationError

from app.bootstrap import build_container, load_settings
from app.infrastructure.config.settings import ConfigurationError, StorageSettings
from app.infrastructure.storage.local_disk import LocalDiskFileStorage
from app.infrastructure.storage.registry import STORAGE_PROVIDERS


def test_storage_defaults() -> None:
    settings = StorageSettings()
    assert settings.provider == "local"
    assert settings.local_directory == Path("var/attachments")
    assert settings.max_bytes == 10 * 1024 * 1024


@pytest.mark.parametrize("value", [0, -1])
def test_limit_is_positive(value: int) -> None:
    with pytest.raises(ValidationError):
        StorageSettings(max_bytes=value)


async def test_storage_settings_and_registry(minimal_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    minimal_env.setenv("STORAGE__LOCAL_DIRECTORY", str(tmp_path))
    minimal_env.setenv("STORAGE__MAX_BYTES", "128")
    container = build_container(load_settings())
    try:
        assert container.settings.storage.max_bytes == 128
        assert isinstance(container.file_storage, LocalDiskFileStorage)
        assert "local" in STORAGE_PROVIDERS
    finally:
        await container.aclose()


def test_unknown_provider_fails_at_startup(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("STORAGE__PROVIDER", "not-registered")
    with pytest.raises(ConfigurationError, match="STORAGE__PROVIDER"):
        build_container(load_settings())
