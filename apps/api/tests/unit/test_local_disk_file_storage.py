"""What only the local-disk adapter can get wrong: the file system under its root."""

import asyncio
import errno
import logging
import os
import stat
import threading
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.application.ports.file_storage import (
    InvalidStorageKeyError,
    StorageKeyTakenError,
    StoredFileNotFound,
)
from app.infrastructure.storage.local_disk import LocalDiskFileStorage

KEY = "0123456789abcdef0123456789abcdef"


async def chunks_of(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def failing_after(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk
    raise ConnectionResetError("the client went away")


def everything_under(directory: Path) -> list[str]:
    return sorted(str(p.relative_to(directory)) for p in directory.rglob("*") if not p.is_dir())


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "var" / "attachments"


@pytest.fixture
def storage(root: Path) -> LocalDiskFileStorage:
    return LocalDiskFileStorage(root)


def test_building_the_adapter_touches_nothing(root: Path, storage: LocalDiskFileStorage) -> None:
    assert not root.exists()


async def test_the_root_appears_with_the_first_file_and_the_file_is_private(
    root: Path, storage: LocalDiskFileStorage
) -> None:
    await storage.save(KEY, chunks_of(b"%PDF-1.7"))

    assert (root / KEY).read_bytes() == b"%PDF-1.7"
    mode = stat.S_IMODE((root / KEY).stat().st_mode)
    assert mode & 0o111 == 0, "a stored file is never executable"
    assert mode & 0o077 == 0, "and readable by its owner only"


async def test_reading_and_deleting_before_anything_was_stored_needs_no_root(
    root: Path, storage: LocalDiskFileStorage
) -> None:
    with pytest.raises(StoredFileNotFound):
        await storage.open(KEY)
    await storage.delete(KEY)

    assert not root.exists()


@pytest.mark.parametrize("key", ["../escaped", "a/../../escaped", "..", "/tmp/escaped"])  # noqa: S108
async def test_no_key_reaches_outside_the_root(
    tmp_path: Path, root: Path, storage: LocalDiskFileStorage, key: str
) -> None:
    with pytest.raises(InvalidStorageKeyError):
        await storage.save(key, chunks_of(b"escaped"))

    assert everything_under(tmp_path) == []
    assert not Path("/tmp/escaped").exists()  # noqa: S108


async def test_an_absolute_key_is_refused_even_when_it_points_inside_the_root(
    root: Path, storage: LocalDiskFileStorage
) -> None:
    with pytest.raises(InvalidStorageKeyError):
        await storage.save(str(root / KEY), chunks_of(b"absolute"))


async def test_a_directory_symlink_inside_the_root_does_not_lead_a_key_outside(
    tmp_path: Path, root: Path, storage: LocalDiskFileStorage
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_bytes(b"not an attachment")
    root.mkdir(parents=True)
    (root / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidStorageKeyError):
        await storage.save("link/planted", chunks_of(b"planted"))
    with pytest.raises(InvalidStorageKeyError):
        await storage.open("link/secret")
    with pytest.raises(InvalidStorageKeyError):
        await storage.delete("link/secret")

    assert everything_under(outside) == ["secret"]
    assert (outside / "secret").read_bytes() == b"not an attachment"


async def test_a_file_symlink_inside_the_root_is_never_followed(
    tmp_path: Path, root: Path, storage: LocalDiskFileStorage
) -> None:
    secret = tmp_path / "secret"
    secret.write_bytes(b"not an attachment")
    root.mkdir(parents=True)
    (root / "link").symlink_to(secret)
    (root / "dangling").symlink_to(tmp_path / "not-there-yet")

    with pytest.raises(InvalidStorageKeyError):
        await storage.open("link")
    with pytest.raises((InvalidStorageKeyError, StorageKeyTakenError)):
        await storage.save("link", chunks_of(b"overwritten"))
    with pytest.raises((InvalidStorageKeyError, StorageKeyTakenError)):
        await storage.save("dangling", chunks_of(b"planted"))
    with pytest.raises(InvalidStorageKeyError):
        await storage.delete("link")

    assert secret.read_bytes() == b"not an attachment"
    assert not (tmp_path / "not-there-yet").exists()


async def test_a_root_that_is_itself_a_symlink_still_works(tmp_path: Path) -> None:
    real = tmp_path / "volume"
    real.mkdir()
    (tmp_path / "attachments").symlink_to(real, target_is_directory=True)
    storage = LocalDiskFileStorage(tmp_path / "attachments")

    await storage.save(KEY, chunks_of(b"through the mount"))

    assert (real / KEY).read_bytes() == b"through the mount"
    assert b"".join([c async for c in await storage.open(KEY)]) == b"through the mount"


async def test_a_directory_is_not_a_stored_file(root: Path, storage: LocalDiskFileStorage) -> None:
    await storage.save("tasks/report", chunks_of(b"nested"))

    with pytest.raises(StoredFileNotFound):
        await storage.open("tasks")
    await storage.delete("tasks")

    assert everything_under(root) == ["tasks/report"]


async def test_a_stream_that_dies_half_way_leaves_no_partial_file(
    root: Path, storage: LocalDiskFileStorage
) -> None:
    with pytest.raises(ConnectionResetError):
        await storage.save(KEY, failing_after(b"x" * 100_000, b"y" * 100_000))

    assert everything_under(root) == []


async def test_cancellation_during_create_removes_the_file(
    root: Path,
    storage: LocalDiskFileStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_create = storage._create
    entered, release = threading.Event(), threading.Event()

    def slow_create(key: str) -> tuple[int, int, str]:
        result = real_create(key)
        entered.set()
        release.wait(timeout=5)
        return result

    monkeypatch.setattr(storage, "_create", slow_create)
    saving = asyncio.create_task(storage.save(KEY, chunks_of(b"data")))
    await asyncio.to_thread(entered.wait, 5)
    saving.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await saving
    assert everything_under(root) == []


async def test_a_disk_that_refuses_the_write_leaves_no_partial_file(
    root: Path, storage: LocalDiskFileStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = os.write
    calls: list[int] = []

    def full_after_the_first_write(descriptor: int, data: bytes) -> int:
        calls.append(descriptor)
        if len(calls) > 1:
            raise OSError(28, "No space left on device")
        return real_write(descriptor, data)

    monkeypatch.setattr(os, "write", full_after_the_first_write)

    with pytest.raises(OSError, match="No space left"):
        await storage.save(KEY, chunks_of(b"first", b"second"))

    assert everything_under(root) == []


async def test_a_cleanup_that_fails_does_not_replace_the_error_that_caused_it(
    root: Path,
    storage: LocalDiskFileStorage,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The caller still learns why the write was abandoned; the orphan is only logged."""

    def refuse(path: str, *, dir_fd: int | None = None) -> None:
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(os, "unlink", refuse)

    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(ConnectionResetError, match="the client went away"),
    ):
        await storage.save(KEY, failing_after(b"half a file"))

    assert everything_under(root) == [KEY]
    assert "Removing the partial file" in caplog.text
