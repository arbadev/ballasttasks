"""Private files below a configured root; descriptor-relative, no-follow traversal.

The root may be a volume symlink. Descendant symlinks are never followed, including
when another process swaps a directory during an operation. Disk I/O runs off-loop.
"""

import asyncio
import errno
import logging
import os
import stat
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO

from app.application.ports.file_storage import (
    InvalidStorageKeyError,
    StorageKeyTakenError,
    StoredFile,
    StoredFileNotFound,
)
from app.domain.storage_key import valid_storage_key

logger = logging.getLogger(__name__)


class LocalDiskFileStorage:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _parent(self, key: str, *, create: bool = False) -> tuple[int, str]:
        if not valid_storage_key(key):
            raise InvalidStorageKeyError("Invalid storage key")
        if create:
            self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            parts = key.split("/")
            for part in parts[:-1]:
                if create:
                    with suppress(FileExistsError):
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                try:
                    child = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                except OSError as exc:
                    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                        raise InvalidStorageKeyError("Invalid storage path") from None
                    raise
                os.close(descriptor)
                descriptor = child
            try:
                info = os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise InvalidStorageKeyError("Invalid storage path")
            except FileNotFoundError:
                pass
            return descriptor, parts[-1]
        except BaseException:
            os.close(descriptor)
            raise

    def _create(self, key: str) -> tuple[int, int, str]:
        parent, name = self._parent(key, create=True)
        try:
            descriptor = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
            )
            return descriptor, parent, name
        except BaseException as exc:
            os.close(parent)
            if isinstance(exc, FileExistsError):
                raise StorageKeyTakenError from None
            raise

    @staticmethod
    def _write(descriptor: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if not written:
                raise OSError("Short write")
            offset += written

    @staticmethod
    async def _remove(name: str, parent: int) -> None:
        """Compensate a write, best effort.

        A cleanup that fails leaves an orphan file and a warning, never an exception in
        place of the one that caused the compensation (ADR 0008).
        """
        try:
            await asyncio.to_thread(os.unlink, name, dir_fd=parent)
        except Exception:
            logger.warning("Removing the partial file %s failed", name)

    async def save(self, key: str, chunks: AsyncIterator[bytes]) -> StoredFile:
        creating = asyncio.create_task(asyncio.to_thread(self._create, key))
        try:
            descriptor, parent, name = await asyncio.shield(creating)
        except asyncio.CancelledError:
            # Threads cannot be cancelled: settle creation before compensating its write.
            descriptor, parent, name = await creating
            try:
                await self._remove(name, parent)
            finally:
                os.close(descriptor)
                os.close(parent)
            raise
        size = 0
        try:
            async for chunk in chunks:
                writing = asyncio.create_task(asyncio.to_thread(self._write, descriptor, chunk))
                try:
                    await asyncio.shield(writing)
                except asyncio.CancelledError:
                    with suppress(Exception):
                        await writing
                    raise
                size += len(chunk)
            return StoredFile(key, size)
        except BaseException:
            await self._remove(name, parent)
            raise
        finally:
            os.close(descriptor)
            os.close(parent)

    def _open(self, key: str) -> BinaryIO:
        try:
            parent, name = self._parent(key)
            try:
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    os.close(descriptor)
                    raise StoredFileNotFound
                return os.fdopen(descriptor, "rb")
            finally:
                os.close(parent)
        except FileNotFoundError:
            raise StoredFileNotFound from None
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise InvalidStorageKeyError("Invalid storage path") from None
            raise

    async def open(self, key: str) -> AsyncIterator[bytes]:
        # The file object also owns closure if the returned iterator is never started.
        opening = asyncio.create_task(asyncio.to_thread(self._open, key))
        try:
            file = await asyncio.shield(opening)
        except asyncio.CancelledError:
            file = await opening
            file.close()
            raise

        async def read() -> AsyncIterator[bytes]:
            try:
                while data := await asyncio.to_thread(file.read, 64 * 1024):
                    yield data
            finally:
                file.close()

        return read()

    def _delete(self, key: str) -> None:
        try:
            parent, name = self._parent(key)
            try:
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISREG(info.st_mode):
                    os.unlink(name, dir_fd=parent)
            finally:
                os.close(parent)
        except FileNotFoundError, IsADirectoryError:
            pass

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)
