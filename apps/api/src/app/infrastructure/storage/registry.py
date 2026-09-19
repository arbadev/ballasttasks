"""Provider name -> factory. A new adapter needs one entry, no use-case edits."""

from collections.abc import Callable

from app.application.ports.file_storage import FileStorage
from app.infrastructure.config.settings import ConfigurationError, StorageSettings
from app.infrastructure.storage.local_disk import LocalDiskFileStorage

STORAGE_PROVIDERS: dict[str, Callable[[StorageSettings], FileStorage]] = {
    "local": lambda settings: LocalDiskFileStorage(settings.local_directory),
}


def build_file_storage(settings: StorageSettings) -> FileStorage:
    factory = STORAGE_PROVIDERS.get(settings.provider)
    if factory is None:
        raise ConfigurationError(
            f"STORAGE__PROVIDER is not registered; choose from {', '.join(STORAGE_PROVIDERS)}"
        )
    return factory(settings)
