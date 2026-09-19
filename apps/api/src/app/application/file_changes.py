"""Compensate file writes on rollback; defer removals until the database commits.

This is not a distributed transaction. Cleanup failure is logged, not substituted
for the original error (or for an already committed success). See ADR 0008.
"""

import logging
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

from app.application.ports.file_storage import FileStorage

logger = logging.getLogger(__name__)


class FileChanges:
    def __init__(self, storage: FileStorage) -> None:
        self._storage = storage
        self._written: set[str] = set()
        self._removed: set[str] = set()

    def written(self, key: str) -> None:
        self._written.add(key)

    def remove_after_commit(self, key: str) -> None:
        self._removed.add(key)

    async def _delete(self, keys: Iterable[str]) -> None:
        for key in keys:
            try:
                await self._storage.delete(key)
            except Exception:
                logger.warning("File cleanup failed for key %s", key)

    async def committed(self) -> None:
        await self._delete(self._removed)

    async def rolled_back(self) -> None:
        await self._delete(self._written)


@asynccontextmanager
async def files_following_the_transaction(storage: FileStorage) -> AsyncIterator[FileChanges]:
    files = FileChanges(storage)
    try:
        yield files
    except BaseException:
        await files.rolled_back()
        raise
    else:
        await files.committed()
