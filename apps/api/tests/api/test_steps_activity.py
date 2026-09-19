"""Steps, comments and the activity feed over HTTP, around a container of fakes.

Every route is reached through the pinned seam (``get_current_user_id``); the caller is
``USER_ID``, stored as "Andres Barradas" so the feed can name them.
"""

import itertools
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.application.use_cases.add_steps import MAX_STEPS_AT_ONCE
from app.bootstrap import build_container, load_settings
from app.domain.step import MAX_STEPS_PER_TASK
from app.infrastructure.rate_limit.in_memory_rate_limiter import InMemoryRateLimiter
from app.main import create_app
from tests.api.conftest import ALL_HEALTHY, USER_ID, AuthFakes, RecordingRequestScopes
from tests.auth_fakes import a_user

NOW = datetime(2026, 3, 10, 9, 30, tzinfo=UTC)
TODAY = date(2026, 3, 10)
UNKNOWN = "00000000-0000-4000-8000-00000000dead"


@pytest.fixture(autouse=True)
def pinned_clock(request_scopes: RecordingRequestScopes) -> None:
    """The day is pinned; the seconds tick, so entries written in a row have an order."""
    ticks = itertools.count()
    request_scopes.clock = lambda: NOW + timedelta(seconds=next(ticks))


@pytest.fixture(autouse=True)
async def me(auth_fakes: AuthFakes) -> None:
    await auth_fakes.users.add(a_user(user_id=USER_ID, full_name="Andres Barradas"))


@pytest.fixture
async def task(task_client: httpx.AsyncClient) -> dict[str, Any]:
    response = await task_client.post("/tasks", json={"title": "Write the report"})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def invalid(kind: str, loc: list[str | int], msg: str) -> dict[str, object]:
    return {"detail": [{"type": kind, "loc": loc, "msg": msg}]}


async def add_step(client: httpx.AsyncClient, task: dict[str, Any], title: str) -> dict[str, Any]:
    response = await client.post(f"/tasks/{task['id']}/steps", json={"title": title})
    assert response.status_code == 201, response.text
    step: dict[str, Any] = response.json()
    return step


async def steps_of(client: httpx.AsyncClient, task: dict[str, Any]) -> list[tuple[str, int, bool]]:
    response = await client.get(f"/tasks/{task['id']}/steps")
    assert response.status_code == 200, response.text
    return [(s["title"], s["position"], s["done"]) for s in response.json()["items"]]


async def activity_of(client: httpx.AsyncClient, task: dict[str, Any]) -> list[str]:
    response = await client.get(f"/tasks/{task['id']}/activity")
    assert response.status_code == 200, response.text
    return [entry["text"] for entry in response.json()["items"]]


# --- steps --------------------------------------------------------------------------------


async def test_a_step_is_created_last_trimmed_and_not_done(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    await add_step(task_client, task, "first")

    response = await task_client.post(f"/tasks/{task['key']}/steps", json={"title": "  second  "})

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body | {"id": None, "created_at": None} == {
        "id": None,
        "task_id": task["id"],
        "title": "second",
        "done": False,
        "position": 1,
        "created_at": None,
    }
    assert datetime.fromisoformat(body["created_at"]).date() == TODAY
    assert await steps_of(task_client, task) == [("first", 0, False), ("second", 1, False)]


async def test_steps_are_created_together_in_the_order_given(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    await add_step(task_client, task, "already here")

    response = await task_client.post(
        f"/tasks/{task['id']}/steps/bulk", json={"titles": ["one", " two ", "three"]}
    )

    assert response.status_code == 201
    assert [(s["title"], s["position"]) for s in response.json()["items"]] == [
        ("one", 1),
        ("two", 2),
        ("three", 3),
    ]
    assert [title for title, _, _ in await steps_of(task_client, task)] == [
        "already here",
        "one",
        "two",
        "three",
    ]


async def test_steps_created_together_are_all_refused_when_one_is_bad(
    task_client: httpx.AsyncClient, task: dict[str, Any], request_scopes: RecordingRequestScopes
) -> None:
    response = await task_client.post(
        f"/tasks/{task['id']}/steps/bulk", json={"titles": ["fine", "nul\x00byte"]}
    )

    assert response.status_code == 422
    assert response.json() == invalid(
        "invalid_step", ["body"], "title must not contain the NUL character"
    )
    assert request_scopes.events[-1] == "rollback"
    assert await steps_of(task_client, task) == []


@pytest.mark.parametrize(
    ("titles", "kind"),
    [
        ([], "too_short"),
        ([f"step {n}" for n in range(21)], "too_long"),
        (["fine", "   "], "string_too_short"),
        (["x" * 201], "string_too_long"),
        ("not a list", "list_type"),
    ],
)
async def test_bulk_creation_rejects_an_invalid_body(
    task_client: httpx.AsyncClient, task: dict[str, Any], titles: object, kind: str
) -> None:
    response = await task_client.post(f"/tasks/{task['id']}/steps/bulk", json={"titles": titles})

    assert response.status_code == 422
    assert [error["type"] for error in response.json()["detail"]] == [kind]
    assert await steps_of(task_client, task) == []


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        ({}, "missing"),
        ({"title": ""}, "string_too_short"),
        ({"title": "   "}, "string_too_short"),
        ({"title": "x" * 201}, "string_too_long"),
        ({"title": None}, "string_type"),
        ({"title": "fine", "done": True}, "extra_forbidden"),
        ({"title": "nul\x00byte"}, "invalid_step"),
    ],
)
async def test_create_rejects_an_invalid_step(
    task_client: httpx.AsyncClient, task: dict[str, Any], body: dict[str, object], kind: str
) -> None:
    response = await task_client.post(f"/tasks/{task['id']}/steps", json=body)

    assert response.status_code == 422
    assert [error["type"] for error in response.json()["detail"]] == [kind]
    assert "input" not in response.json()["detail"][0]
    assert await steps_of(task_client, task) == []


async def test_a_title_of_exactly_200_characters_after_trimming_is_accepted(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    step = await add_step(task_client, task, "  " + "x" * 200 + "  ")

    assert len(step["title"]) == 200


async def fill_with_steps(client: httpx.AsyncClient, task: dict[str, Any], count: int) -> None:
    """``count`` steps, in batches of the most that can be accepted at once."""
    for first in range(0, count, MAX_STEPS_AT_ONCE):
        titles = [f"step {n}" for n in range(first, min(first + MAX_STEPS_AT_ONCE, count))]
        response = await client.post(f"/tasks/{task['id']}/steps/bulk", json={"titles": titles})
        assert response.status_code == 201, response.text


async def test_a_task_holds_a_hundred_steps_and_says_so_when_asked_for_more(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    await fill_with_steps(task_client, task, MAX_STEPS_PER_TASK)

    one_more = await task_client.post(f"/tasks/{task['id']}/steps", json={"title": "one too many"})
    together = await task_client.post(
        f"/tasks/{task['id']}/steps/bulk", json={"titles": ["one too many"]}
    )

    assert (one_more.status_code, together.status_code) == (422, 422)
    assert one_more.json() == invalid(
        "invalid_step", ["body"], f"a task may hold at most {MAX_STEPS_PER_TASK} steps"
    )
    assert together.json() == one_more.json()
    assert len(await steps_of(task_client, task)) == MAX_STEPS_PER_TASK


async def test_steps_accepted_together_are_all_refused_when_they_would_not_all_fit(
    task_client: httpx.AsyncClient, task: dict[str, Any], request_scopes: RecordingRequestScopes
) -> None:
    await fill_with_steps(task_client, task, MAX_STEPS_PER_TASK - 2)

    response = await task_client.post(
        f"/tasks/{task['id']}/steps/bulk", json={"titles": ["one", "two", "three"]}
    )

    assert response.status_code == 422
    assert response.json() == invalid(
        "invalid_step", ["body"], f"a task may hold at most {MAX_STEPS_PER_TASK} steps"
    )
    assert request_scopes.events[-1] == "rollback"
    assert len(await steps_of(task_client, task)) == MAX_STEPS_PER_TASK - 2


async def test_a_step_is_renamed_and_ticked(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    step = await add_step(task_client, task, "Write the test")
    path = f"/tasks/{task['id']}/steps/{step['id']}"

    renamed = await task_client.patch(path, json={"title": " Write the failing test "})
    ticked = await task_client.patch(path, json={"done": True})
    unticked = await task_client.patch(path, json={"done": False, "title": "Back again"})

    assert (renamed.status_code, ticked.status_code, unticked.status_code) == (200, 200, 200)
    assert (renamed.json()["title"], renamed.json()["done"]) == ("Write the failing test", False)
    assert (ticked.json()["title"], ticked.json()["done"]) == ("Write the failing test", True)
    assert unticked.json() == step | {"title": "Back again", "done": False}


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        ({"title": None}, "value_error"),
        ({"done": None}, "value_error"),
        ({"title": "  "}, "string_too_short"),
        ({"done": "perhaps"}, "bool_parsing"),
        ({"position": 3}, "extra_forbidden"),
        ({"title": "nul\x00byte"}, "invalid_step"),
    ],
)
async def test_patch_rejects_an_invalid_change_and_leaves_the_step_alone(
    task_client: httpx.AsyncClient, task: dict[str, Any], body: dict[str, object], kind: str
) -> None:
    step = await add_step(task_client, task, "Write the test")

    response = await task_client.patch(f"/tasks/{task['id']}/steps/{step['id']}", json=body)

    assert response.status_code == 422
    assert [error["type"] for error in response.json()["detail"]] == [kind]
    assert await steps_of(task_client, task) == [("Write the test", 0, False)]


async def test_steps_are_reordered_by_naming_them_all(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    a, b, c = [await add_step(task_client, task, title) for title in "abc"]

    response = await task_client.put(
        f"/tasks/{task['id']}/steps/order", json={"step_ids": [c["id"], a["id"], b["id"]]}
    )

    assert response.status_code == 200
    assert [(s["title"], s["position"]) for s in response.json()["items"]] == [
        ("c", 0),
        ("a", 1),
        ("b", 2),
    ]
    assert await steps_of(task_client, task) == [("c", 0, False), ("a", 1, False), ("b", 2, False)]


async def test_an_order_that_is_not_every_step_exactly_once_is_refused(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    a, b = [await add_step(task_client, task, title) for title in "ab"]

    for step_ids in ([a["id"]], [a["id"], a["id"]], [a["id"], b["id"], UNKNOWN]):
        response = await task_client.put(
            f"/tasks/{task['id']}/steps/order", json={"step_ids": step_ids}
        )
        assert response.status_code == 422
        assert response.json() == invalid(
            "invalid_step_order",
            ["body", "step_ids"],
            "step_ids must name every step of the task exactly once",
        )

    assert await steps_of(task_client, task) == [("a", 0, False), ("b", 1, False)]


async def test_a_task_with_every_step_it_may_hold_is_reordered_but_a_longer_order_is_refused(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    """The order names at most the steps a task may hold: one id more is refused by the
    schema, before the task is read or anything moves."""
    await fill_with_steps(task_client, task, MAX_STEPS_PER_TASK)
    listed = (await task_client.get(f"/tasks/{task['id']}/steps")).json()["items"]
    ids = [step["id"] for step in listed]
    upside_down = list(reversed([step["title"] for step in listed]))

    reordered = await task_client.put(
        f"/tasks/{task['id']}/steps/order", json={"step_ids": list(reversed(ids))}
    )
    one_id_too_many = await task_client.put(
        f"/tasks/{task['id']}/steps/order", json={"step_ids": [*ids, UNKNOWN]}
    )

    assert reordered.status_code == 200, reordered.text
    assert [step["title"] for step in reordered.json()["items"]] == upside_down
    assert one_id_too_many.status_code == 422
    assert [error["type"] for error in one_id_too_many.json()["detail"]] == ["too_long"]
    assert await steps_of(task_client, task) == [
        (title, position, False) for position, title in enumerate(upside_down)
    ]


async def test_a_task_without_steps_accepts_the_only_order_there_is(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    response = await task_client.put(f"/tasks/{task['id']}/steps/order", json={"step_ids": []})

    assert response.status_code == 200
    assert response.json() == {"items": []}


async def test_a_deleted_step_is_gone_and_the_rest_close_up(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    _, b, _ = [await add_step(task_client, task, title) for title in "abc"]

    response = await task_client.delete(f"/tasks/{task['id']}/steps/{b['id']}")

    assert (response.status_code, response.content) == (204, b"")
    assert await steps_of(task_client, task) == [("a", 0, False), ("c", 1, False)]
    again = await task_client.delete(f"/tasks/{task['id']}/steps/{b['id']}")
    assert (again.status_code, again.json()) == (404, {"detail": f"Step {b['id']} not found"})


async def test_a_step_is_only_reached_through_its_own_task(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    step = await add_step(task_client, task, "mine")
    other = (await task_client.post("/tasks", json={"title": "Another task"})).json()

    through_another = f"/tasks/{other['id']}/steps/{step['id']}"
    assert (await task_client.patch(through_another, json={"done": True})).status_code == 404
    assert (await task_client.delete(through_another)).status_code == 404
    assert await steps_of(task_client, task) == [("mine", 0, False)]


# --- the task representations --------------------------------------------------------------


async def test_every_task_representation_counts_its_steps_and_comments(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    assert (task["steps_total"], task["steps_done"], task["comments_count"]) == (0, 0, 0)
    first = await add_step(task_client, task, "first")
    await add_step(task_client, task, "second")
    await task_client.patch(f"/tasks/{task['id']}/steps/{first['id']}", json={"done": True})
    for text in ("one", "two", "three"):
        await task_client.post(f"/tasks/{task['id']}/comments", json={"text": text})
    quiet = (await task_client.post("/tasks", json={"title": "Quiet task"})).json()

    counted = {"steps_total": 2, "steps_done": 1, "comments_count": 3}
    one = (await task_client.get(f"/tasks/{task['id']}")).json()
    patched = (await task_client.patch(f"/tasks/{task['id']}", json={"importance": 60})).json()
    listed = {t["id"]: t for t in (await task_client.get("/tasks")).json()["items"]}

    for representation in (one, patched, listed[task["id"]]):
        assert {name: representation[name] for name in counted} == counted
    assert {name: listed[quiet["id"]][name] for name in counted} == dict.fromkeys(counted, 0)


async def test_one_task_is_read_with_its_steps_in_order_and_the_list_without(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    a, b = [await add_step(task_client, task, title) for title in "ab"]
    await task_client.put(f"/tasks/{task['id']}/steps/order", json={"step_ids": [b["id"], a["id"]]})

    one = (await task_client.get(f"/tasks/{task['key']}")).json()
    (listed,) = (await task_client.get("/tasks")).json()["items"]

    assert one["steps"] == [b | {"position": 0}, a | {"position": 1}]
    assert "steps" not in listed
    assert "steps" not in task


async def test_deleting_a_task_takes_its_steps_and_activity_with_it(
    task_client: httpx.AsyncClient, task: dict[str, Any], request_scopes: RecordingRequestScopes
) -> None:
    await add_step(task_client, task, "doomed")

    assert (await task_client.delete(f"/tasks/{task['id']}")).status_code == 204

    assert (await task_client.get(f"/tasks/{task['id']}/steps")).status_code == 404
    assert list(await request_scopes.steps.list_for_task(uuid.UUID(task["id"]))) == []
    assert request_scopes.activity.entries == []


# --- the activity log ------------------------------------------------------------------------


async def test_what_happens_to_a_task_is_logged_in_the_design_s_words(
    task_client: httpx.AsyncClient, task: dict[str, Any], auth_fakes: AuthFakes
) -> None:
    lucia = a_user(full_name="Lucía Marín")
    await auth_fakes.users.add(lucia)
    path = f"/tasks/{task['id']}"

    await task_client.patch(path, json={"status": "in_progress"})
    await task_client.patch(path, json={"assignee_id": str(lucia.id)})
    await task_client.patch(path, json={"due_date": (TODAY + timedelta(days=1)).isoformat()})
    await task_client.patch(path, json={"priority": "P0"})
    step = await add_step(task_client, task, "Write the test")
    await task_client.patch(f"{path}/steps/{step['id']}", json={"done": True})
    await task_client.post(f"{path}/steps/bulk", json={"titles": ["one", "two"]})
    await task_client.patch(path, json={"status": "done"})
    await task_client.patch(path, json={"status": "todo", "assignee_id": None})

    assert await activity_of(task_client, task) == [
        "Unassigned",
        "Moved Done → To Do",
        "Moved In Progress → Done",
        "Drafted 2 steps · added by Andres",
        "Completed step “Write the test”",
        "Added step “Write the test”",
        "Priority P2 → P0",
        "Due date moved to tomorrow",
        "Assigned to Lucía Marín",
        "Moved To Do → In Progress",
        "Created the task",
    ]


async def test_a_change_that_alters_nothing_is_not_logged(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    step = await add_step(task_client, task, "Write the test")
    path = f"/tasks/{task['id']}"

    await task_client.patch(path, json={"status": "todo", "priority": "P2", "due_date": None})
    await task_client.patch(path, json={"title": "Another title", "importance": 10})
    await task_client.patch(f"{path}/steps/{step['id']}", json={"done": False})
    await task_client.patch(f"{path}/steps/{step['id']}", json={"title": "Renamed"})
    await task_client.put(f"{path}/steps/order", json={"step_ids": [step["id"]]})
    await task_client.delete(f"{path}/steps/{step['id']}")

    assert await activity_of(task_client, task) == [
        "Added step “Write the test”",
        "Created the task",
    ]


async def test_a_change_that_is_refused_is_not_logged(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    response = await task_client.patch(
        f"/tasks/{task['id']}", json={"status": "done", "assignee_id": UNKNOWN}
    )

    assert response.status_code == 422
    assert await activity_of(task_client, task) == ["Created the task"]


# --- comments and the feed -------------------------------------------------------------------


async def test_a_comment_is_an_entry_by_the_caller(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    response = await task_client.post(
        f"/tasks/{task['key']}/comments", json={"text": "  Looks good to me \n"}
    )

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body | {"id": None, "created_at": None} == {
        "id": None,
        "task_id": task["id"],
        "kind": "comment",
        "text": "Looks good to me",
        "actor": {"id": str(USER_ID), "full_name": "Andres Barradas", "initials": "AB"},
        "created_at": None,
    }
    feed = (await task_client.get(f"/tasks/{task['id']}/activity")).json()
    assert feed["items"][0] == body


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        ({}, "missing"),
        ({"text": ""}, "string_too_short"),
        ({"text": " \n "}, "string_too_short"),
        ({"text": "x" * 2001}, "string_too_long"),
        ({"text": None}, "string_type"),
        ({"text": "fine", "kind": "log"}, "extra_forbidden"),
        ({"text": "fine", "actor_id": UNKNOWN}, "extra_forbidden"),
        ({"text": "nul\x00byte"}, "invalid_comment"),
    ],
)
async def test_a_comment_that_cannot_be_stored_is_refused(
    task_client: httpx.AsyncClient, task: dict[str, Any], body: dict[str, object], kind: str
) -> None:
    response = await task_client.post(f"/tasks/{task['id']}/comments", json=body)

    assert response.status_code == 422
    assert [error["type"] for error in response.json()["detail"]] == [kind]
    assert await activity_of(task_client, task) == ["Created the task"]


async def test_a_comment_of_exactly_2000_characters_after_trimming_is_accepted(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    response = await task_client.post(
        f"/tasks/{task['id']}/comments", json={"text": " " + "x" * 2000 + " "}
    )

    assert response.status_code == 201
    assert len(response.json()["text"]) == 2000


async def test_comments_cannot_be_edited_or_deleted(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    comment = (await task_client.post(f"/tasks/{task['id']}/comments", json={"text": "hi"})).json()

    for path in (
        f"/tasks/{task['id']}/comments/{comment['id']}",
        f"/tasks/{task['id']}/activity/{comment['id']}",
    ):
        for method in ("PATCH", "PUT", "DELETE"):
            response = await task_client.request(method, path, json={"text": "changed"})
            assert response.status_code in (404, 405)
    assert await activity_of(task_client, task) == ["hi", "Created the task"]


async def test_the_feed_is_an_envelope_newest_first_with_names_and_no_email(
    task_client: httpx.AsyncClient, task: dict[str, Any], auth_fakes: AuthFakes
) -> None:
    for n in range(4):
        await task_client.post(f"/tasks/{task['id']}/comments", json={"text": f"comment {n}"})

    everything = (await task_client.get(f"/tasks/{task['id']}/activity")).json()
    page = (await task_client.get(f"/tasks/{task['id']}/activity?limit=2&offset=1")).json()

    assert [e["text"] for e in everything["items"]] == [
        "comment 3",
        "comment 2",
        "comment 1",
        "comment 0",
        "Created the task",
    ]
    assert (everything["total"], everything["limit"], everything["offset"]) == (5, 50, 0)
    assert [e["kind"] for e in everything["items"]] == ["comment"] * 4 + ["log"]
    assert [e["text"] for e in page["items"]] == ["comment 2", "comment 1"]
    assert (page["total"], page["limit"], page["offset"]) == (5, 2, 1)
    me = await auth_fakes.users.get_by_id(USER_ID)
    assert me is not None
    assert me.email not in str(everything)
    assert set(everything["items"][0]["actor"]) == {"id", "full_name", "initials"}


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=201", "offset=-1", "limit=many", "page=2", "kind=comment"]
)
async def test_the_feed_rejects_parameters_it_does_not_understand(
    task_client: httpx.AsyncClient, task: dict[str, Any], query: str
) -> None:
    response = await task_client.get(f"/tasks/{task['id']}/activity?{query}")

    assert response.status_code == 422


# --- what every new route shares ---------------------------------------------------------------

NEW_ROUTES = [
    ("GET", "/steps", None),
    ("POST", "/steps", {"title": "a step"}),
    ("POST", "/steps/bulk", {"titles": ["a step"]}),
    ("PUT", "/steps/order", {"step_ids": []}),
    ("PATCH", f"/steps/{UNKNOWN}", {"done": True}),
    ("DELETE", f"/steps/{UNKNOWN}", None),
    ("POST", "/comments", {"text": "a comment"}),
    ("GET", "/activity", None),
]


@pytest.mark.parametrize(("method", "path", "body"), NEW_ROUTES)
async def test_every_new_route_needs_a_signed_in_caller(
    anonymous_client: httpx.AsyncClient, method: str, path: str, body: object
) -> None:
    response = await anonymous_client.request(method, f"/tasks/{UNKNOWN}{path}", json=body)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(("method", "path", "body"), NEW_ROUTES)
@pytest.mark.parametrize("reference", [UNKNOWN, "BT-404"])
async def test_every_new_route_is_404_for_a_task_that_does_not_exist(
    task_client: httpx.AsyncClient, method: str, path: str, body: object, reference: str
) -> None:
    response = await task_client.request(method, f"/tasks/{reference}{path}", json=body)

    assert response.status_code == 404
    assert response.json()["detail"].startswith("Task ")
    assert response.json()["detail"].endswith(" not found")


@pytest.mark.parametrize(("method", "path", "body"), NEW_ROUTES)
async def test_every_new_route_is_422_for_a_reference_that_is_neither_an_id_nor_a_key(
    task_client: httpx.AsyncClient, method: str, path: str, body: object
) -> None:
    response = await task_client.request(method, f"/tasks/not-a-reference{path}", json=body)

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "invalid_task_reference"


async def test_a_step_id_that_is_not_a_uuid_is_422(
    task_client: httpx.AsyncClient, task: dict[str, Any]
) -> None:
    response = await task_client.patch(f"/tasks/{task['id']}/steps/first", json={"done": True})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "step_id"]


@pytest.fixture
async def limited_app(
    minimal_env: pytest.MonkeyPatch, request_scopes: RecordingRequestScopes
) -> AsyncIterator[FastAPI]:
    """The real app with a budget of two anonymous requests, counted in memory."""
    minimal_env.setenv("RATE_LIMIT__ANONYMOUS__LIMIT", "2")
    container = build_container(load_settings())
    app = create_app(
        container=replace(
            container,
            health_checks=ALL_HEALTHY,
            request_scope=request_scopes,
            rate_limiting=replace(container.rate_limiting, limiter=InMemoryRateLimiter()),
        )
    )
    async with app.router.lifespan_context(app):
        yield app


@pytest.mark.parametrize(("method", "path", "body"), NEW_ROUTES)
async def test_every_new_route_is_rate_limited_before_anything_else(
    limited_app: FastAPI, method: str, path: str, body: object
) -> None:
    transport = httpx.ASGITransport(app=limited_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = [
            await client.request(method, f"/tasks/{UNKNOWN}{path}", json=body) for _ in range(3)
        ]

    assert [response.status_code for response in responses] == [401, 401, 429]
    assert responses[0].headers["x-ratelimit-limit"] == "2"
    assert responses[-1].json() == {"detail": "Too many requests"}
    assert "retry-after" in responses[-1].headers
