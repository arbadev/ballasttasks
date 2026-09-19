"""Files follow the transaction: what a rolled-back unit of work wrote is deleted, and what a
committed one removed is deleted only then."""

import asyncio
import logging
from collections.abc import AsyncIterator

import pytest
from app.application.file_changes import FileChanges, files_following_the_transaction
from app.infrastructure.storage.in_memory import InMemoryFileStorage


async def chunks_of(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


@pytest.fixture
async def storage() -> InMemoryFileStorage:
    storage = InMemoryFileStorage()
    await storage.save("old", chunks_of(b"attached last week"))
    return storage


class CommitFailedError(Exception):
    pass


async def a_unit_of_work_that_writes_new_removes_old_and_then(
    storage: InMemoryFileStorage, error: BaseException
) -> None:
    async with files_following_the_transaction(storage) as files:
        await storage.save("new", chunks_of(b"attached now"))
        files.written("new")
        files.remove_after_commit("old")
        raise error


async def test_a_unit_of_work_that_ends_well_keeps_what_it_wrote_and_deletes_what_it_removed(
    storage: InMemoryFileStorage,
) -> None:
    async with files_following_the_transaction(storage) as files:
        await storage.save("new", chunks_of(b"attached now"))
        files.written("new")
        files.remove_after_commit("old")
        assert storage.stored_keys() == ["new", "old"], "nothing is deleted before the commit"

    assert storage.stored_keys() == ["new"]


async def test_a_unit_of_work_that_fails_deletes_what_it_wrote_and_keeps_what_it_would_have_removed(
    storage: InMemoryFileStorage,
) -> None:
    with pytest.raises(CommitFailedError):
        await a_unit_of_work_that_writes_new_removes_old_and_then(storage, CommitFailedError())

    assert storage.stored_keys() == ["old"]


async def test_a_cancelled_request_is_a_failed_unit_of_work(storage: InMemoryFileStorage) -> None:
    with pytest.raises(asyncio.CancelledError):
        await a_unit_of_work_that_writes_new_removes_old_and_then(storage, asyncio.CancelledError())

    assert storage.stored_keys() == ["old"]


class BrokenStorage(InMemoryFileStorage):
    async def delete(self, key: str) -> None:
        raise OSError(f"cannot delete {key}")


async def test_a_storage_that_cannot_delete_never_turns_a_committed_request_into_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = BrokenStorage()
    await storage.save("old", chunks_of(b"x"))

    with caplog.at_level(logging.WARNING):
        async with files_following_the_transaction(storage) as files:
            files.remove_after_commit("old")
            files.remove_after_commit("older")

    assert [record.levelname for record in caplog.records] == ["WARNING", "WARNING"]
    assert "old" in caplog.text


async def test_a_storage_that_cannot_delete_does_not_hide_why_the_unit_of_work_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = BrokenStorage()
    await storage.save("old", chunks_of(b"x"))

    with pytest.raises(CommitFailedError), caplog.at_level(logging.WARNING):
        await a_unit_of_work_that_writes_new_removes_old_and_then(storage, CommitFailedError())

    assert "new" in caplog.text


async def test_changes_can_be_settled_by_hand(storage: InMemoryFileStorage) -> None:
    files = FileChanges(storage)
    files.remove_after_commit("old")

    await files.rolled_back()
    assert storage.stored_keys() == ["old"]

    await files.committed()
    assert storage.stored_keys() == []
