"""Streaming storage. Saves are exclusive and remove partial writes on failure.

Open must report absence before returning the iterator. Delete is idempotent.
Adapters validate keys on every operation, and never follow paths outside their root.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


class InvalidStorageKeyError(ValueError):
    pass


class StorageKeyTakenError(Exception):
    pass


class StoredFileNotFound(Exception):  # noqa: N818 - mirrors the repository's NotFound errors
    pass


@dataclass(frozen=True, slots=True)
class StoredFile:
    key: str
    size_bytes: int


class FileStorage(Protocol):
    async def save(self, key: str, chunks: AsyncIterator[bytes]) -> StoredFile: ...
    async def open(self, key: str) -> AsyncIterator[bytes]: ...
    async def delete(self, key: str) -> None: ...
