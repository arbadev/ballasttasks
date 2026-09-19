"""Contract every ActivityRecorder and ActivityFeed adapter must honour (Liskov).

Two ports, one suite: what one records is what the other reads. The store: ``conftest.py``.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.application.ports.activity_feed import ActivityItem
from app.domain.activity import ActivityEntry, Actor
from tests.contract.conftest import TaskSideStore

# PostgreSQL keeps microseconds, so this value survives a round trip unchanged.
NOW = datetime(2026, 1, 5, 9, 0, 0, 123456, tzinfo=UTC)


def a_log(task_id: uuid.UUID, actor_id: uuid.UUID, text: str, at: datetime = NOW) -> ActivityEntry:
    return ActivityEntry.log(
        entry_id=uuid.uuid4(), task_id=task_id, actor_id=actor_id, text=text, now=at
    )


def a_comment(
    task_id: uuid.UUID, actor_id: uuid.UUID, text: str, at: datetime = NOW
) -> ActivityEntry:
    return ActivityEntry.comment(
        entry_id=uuid.uuid4(), task_id=task_id, actor_id=actor_id, text=text, now=at
    )


async def test_a_task_nothing_happened_to_has_an_empty_page(task_side: TaskSideStore) -> None:
    task = await task_side.a_stored_task()

    for task_id in (task.id, uuid.uuid4()):
        page = await task_side.feed.page(task_id, limit=50, offset=0)
        assert (list(page.items), page.total) == ([], 0)


async def test_a_recorded_entry_is_read_back_with_the_name_of_who_it_is_by(
    task_side: TaskSideStore,
) -> None:
    lucia = await task_side.a_stored_user(full_name="Lucía Marín")
    task = await task_side.a_stored_task(lucia)
    entry = a_comment(task.id, lucia.id, "Ünïcode “quoted” → comment")

    await task_side.recorder.record(entry)

    page = await task_side.feed.page(task.id, limit=50, offset=0)
    assert list(page.items) == [ActivityItem(entry, Actor(id=lucia.id, full_name="Lucía Marín"))]
    assert page.items[0].actor.initials == "LM"
    assert page.total == 1


async def test_the_newest_entry_comes_first(task_side: TaskSideStore) -> None:
    user = await task_side.a_stored_user()
    task = await task_side.a_stored_task(user)
    middle = a_log(task.id, user.id, "middle", NOW + timedelta(hours=1))
    oldest = a_log(task.id, user.id, "oldest", NOW)
    newest = a_comment(task.id, user.id, "newest", NOW + timedelta(hours=2))
    for entry in (middle, oldest, newest):
        await task_side.recorder.record(entry)

    page = await task_side.feed.page(task.id, limit=50, offset=0)

    assert [item.entry.text for item in page.items] == ["newest", "middle", "oldest"]


async def test_entries_of_the_same_instant_come_last_recorded_first(
    task_side: TaskSideStore,
) -> None:
    """One PATCH can leave several lines at one instant; their order must not be left to
    their random ids."""
    user = await task_side.a_stored_user()
    task = await task_side.a_stored_task(user)
    texts = [f"line {n}" for n in range(8)]
    for text in texts:
        await task_side.recorder.record(a_log(task.id, user.id, text))

    page = await task_side.feed.page(task.id, limit=50, offset=0)

    assert [item.entry.text for item in page.items] == list(reversed(texts))


async def test_pages_do_not_overlap_and_the_total_counts_everything(
    task_side: TaskSideStore,
) -> None:
    user = await task_side.a_stored_user()
    task = await task_side.a_stored_task(user)
    for n in range(5):
        await task_side.recorder.record(
            a_log(task.id, user.id, f"entry {n}", NOW + timedelta(minutes=n))
        )

    first = await task_side.feed.page(task.id, limit=2, offset=0)
    second = await task_side.feed.page(task.id, limit=2, offset=2)
    last = await task_side.feed.page(task.id, limit=2, offset=4)
    beyond = await task_side.feed.page(task.id, limit=2, offset=9)

    assert [item.entry.text for item in first.items] == ["entry 4", "entry 3"]
    assert [item.entry.text for item in second.items] == ["entry 2", "entry 1"]
    assert [item.entry.text for item in last.items] == ["entry 0"]
    assert list(beyond.items) == []
    assert first.total == second.total == last.total == beyond.total == 5


async def test_only_the_entries_of_that_task_are_read(task_side: TaskSideStore) -> None:
    user = await task_side.a_stored_user()
    task, other = await task_side.a_stored_task(user), await task_side.a_stored_task(user)
    await task_side.recorder.record(a_log(task.id, user.id, "mine"))
    await task_side.recorder.record(a_log(other.id, user.id, "theirs"))

    page = await task_side.feed.page(task.id, limit=50, offset=0)

    assert ([item.entry.text for item in page.items], page.total) == (["mine"], 1)


async def test_an_entry_by_somebody_since_deactivated_still_names_them(
    task_side: TaskSideStore,
) -> None:
    gone = await task_side.a_stored_user(full_name="Grace Hopper", is_active=False)
    task = await task_side.a_stored_task()
    await task_side.recorder.record(a_comment(task.id, gone.id, "I was here"))

    page = await task_side.feed.page(task.id, limit=50, offset=0)

    assert page.items[0].actor == Actor(id=gone.id, full_name="Grace Hopper")


async def test_deleting_a_task_deletes_its_activity(task_side: TaskSideStore) -> None:
    user = await task_side.a_stored_user()
    task, other = await task_side.a_stored_task(user), await task_side.a_stored_task(user)
    await task_side.recorder.record(a_log(task.id, user.id, "doomed"))
    await task_side.recorder.record(a_log(other.id, user.id, "kept"))

    await task_side.tasks.delete(task.id)

    assert (await task_side.feed.page(task.id, limit=50, offset=0)).total == 0
    assert (await task_side.feed.page(other.id, limit=50, offset=0)).total == 1
