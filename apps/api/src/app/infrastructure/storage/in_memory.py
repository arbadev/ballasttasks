"""In-memory FileStorage fake: the same exclusive keys and failure semantics."""

from collections.abc import AsyncIterator

from app.application.ports.file_storage import (
    InvalidStorageKeyError,
    StorageKeyTakenError,
    StoredFile,
    StoredFileNotFound,
)
from app.domain.storage_key import valid_storage_key


class InMemoryFileStorage:
    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}
        self._writing: set[str] = set()

    @staticmethod
    def _validate(key: str) -> None:
        if not valid_storage_key(key):
            raise InvalidStorageKeyError("Invalid storage key")

    async def save(self, key: str, chunks: AsyncIterator[bytes]) -> StoredFile:
        self._validate(key)
        if key in self._files or key in self._writing:
            raise StorageKeyTakenError
        self._writing.add(key)
        try:
            data = bytearray()
            async for chunk in chunks:
                data.extend(chunk)
            self._files[key] = bytes(data)
            return StoredFile(key, len(data))
        finally:
            self._writing.remove(key)

    async def open(self, key: str) -> AsyncIterator[bytes]:
        self._validate(key)
        if key not in self._files:
            raise StoredFileNotFound
        data = self._files[key]

        async def read() -> AsyncIterator[bytes]:
            for offset in range(0, len(data), 64 * 1024):
                yield data[offset : offset + 64 * 1024]

        return read()

    async def delete(self, key: str) -> None:
        self._validate(key)
        self._files.pop(key, None)

    def stored_keys(self) -> list[str]:
        return sorted(self._files)
