"""Contract every FileStorage adapter must honour.

The in-memory adapter the unit and API tests rely on runs here next to the local-disk one
(in a temporary directory under the integration marker). A future
S3 or Cloudinary adapter is one new entry in ``ADAPTERS`` and one branch in ``storage``.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.application.ports.file_storage import (
    FileStorage,
    InvalidStorageKeyError,
    StorageKeyTakenError,
    StoredFile,
    StoredFileNotFound,
)
from app.infrastructure.storage.in_memory import InMemoryFileStorage
from app.infrastructure.storage.local_disk import LocalDiskFileStorage

ADAPTERS = ["in-memory", pytest.param("local-disk", marks=pytest.mark.integration)]
KEY = "0123456789abcdef0123456789abcdef"

INVALID_KEYS = [
    "",
    ".",
    "..",
    "../outside",
    "a/../../outside",
    "a/./b",
    "/etc/passwd",
    "//double",
    "a//b",
    "a/",
    "..\\outside",
    "C:\\outside",
    "a\\b",
    ".hidden",
    "a/.hidden",
    "~/home",
    "with space",
    "nul\x00byte",
    "new\nline",
    "r\u00e9sum\u00e9",
    "x" * 201,
]


@pytest.fixture(params=ADAPTERS)
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> FileStorage:
    if request.param == "in-memory":
        return InMemoryFileStorage()
    return LocalDiskFileStorage(tmp_path / "attachments")


async def chunks_of(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def content_of(storage: FileStorage, key: str) -> bytes:
    return b"".join([chunk async for chunk in await storage.open(key)])


class StreamBrokeError(Exception):
    pass


async def breaking_after(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk
    raise StreamBrokeError


async def test_what_was_saved_is_what_is_read_back(storage: FileStorage) -> None:
    stored = await storage.save(KEY, chunks_of(b"%PDF-", b"1.7\n", b"", b"the rest"))

    assert stored == StoredFile(key=KEY, size_bytes=17)
    assert await content_of(storage, KEY) == b"%PDF-1.7\nthe rest"


async def test_a_file_larger_than_any_buffer_survives_the_round_trip(storage: FileStorage) -> None:
    block = bytes(range(256)) * 1024  # 256 KiB
    stored = await storage.save(KEY, chunks_of(*[block] * 9, b"tail"))

    assert stored.size_bytes == 9 * len(block) + 4
    read = [chunk async for chunk in await storage.open(KEY)]
    assert b"".join(read) == block * 9 + b"tail"
    assert len(read) > 1, "a file is streamed back in pieces, never as one buffer"


async def test_an_empty_stream_stores_an_empty_file(storage: FileStorage) -> None:
    assert (await storage.save(KEY, chunks_of())).size_bytes == 0
    assert await content_of(storage, KEY) == b""


async def test_a_key_may_have_segments(storage: FileStorage) -> None:
    await storage.save("tasks/2026/report-1.pdf", chunks_of(b"nested"))

    assert await content_of(storage, "tasks/2026/report-1.pdf") == b"nested"


async def test_files_are_kept_apart_by_key(storage: FileStorage) -> None:
    await storage.save("one", chunks_of(b"first"))
    await storage.save("two", chunks_of(b"second"))

    assert (await content_of(storage, "one"), await content_of(storage, "two")) == (
        b"first",
        b"second",
    )


async def test_a_taken_key_is_refused_and_the_first_file_is_untouched(storage: FileStorage) -> None:
    await storage.save(KEY, chunks_of(b"first"))

    with pytest.raises(StorageKeyTakenError):
        await storage.save(KEY, chunks_of(b"second"))

    assert await content_of(storage, KEY) == b"first"


async def test_a_stream_that_fails_half_way_leaves_nothing_under_the_key(
    storage: FileStorage,
) -> None:
    with pytest.raises(StreamBrokeError):
        await storage.save(KEY, breaking_after(b"half", b" of it"))

    with pytest.raises(StoredFileNotFound):
        await storage.open(KEY)
    # The key is free again, not half taken.
    await storage.save(KEY, chunks_of(b"whole"))
    assert await content_of(storage, KEY) == b"whole"


async def test_opening_what_is_not_stored_raises_before_anything_is_read(
    storage: FileStorage,
) -> None:
    with pytest.raises(StoredFileNotFound):
        await storage.open(KEY)


async def test_delete_removes_the_file_and_deleting_again_is_not_an_error(
    storage: FileStorage,
) -> None:
    await storage.save(KEY, chunks_of(b"gone soon"))
    await storage.save("kept", chunks_of(b"kept"))

    await storage.delete(KEY)
    await storage.delete(KEY)
    await storage.delete("never-stored")

    with pytest.raises(StoredFileNotFound):
        await storage.open(KEY)
    assert await content_of(storage, "kept") == b"kept"


async def test_deleting_a_directory_key_is_a_no_op(storage: FileStorage) -> None:
    await storage.save("tasks/report", chunks_of(b"kept"))

    await storage.delete("tasks")

    assert await content_of(storage, "tasks/report") == b"kept"


@pytest.mark.parametrize("key", INVALID_KEYS)
async def test_a_key_the_server_would_never_generate_is_refused_everywhere(
    storage: FileStorage, key: str
) -> None:
    consumed: list[bytes] = []

    async def recording() -> AsyncIterator[bytes]:
        consumed.append(b"read")
        yield b"never written"

    with pytest.raises(InvalidStorageKeyError):
        await storage.save(key, recording())
    with pytest.raises(InvalidStorageKeyError):
        await storage.open(key)
    with pytest.raises(InvalidStorageKeyError):
        await storage.delete(key)
    assert consumed == [], "a refused key costs nothing: the stream is not even started"
