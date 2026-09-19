"""The design's task contract over HTTP: projects and keys, priority and importance, the
attention object, the list parameters and the summary.

What each filter and sort MEANS is pinned once, for every adapter, in
``tests/contract/test_task_repository_contract.py``; these tests pin how a request reaches it.
"""

import itertools
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.api.schemas.tasks import TaskListResponse, TaskResponse, TaskSummaryResponse
from app.domain.project import DEFAULT_PROJECT_ID
from tests.api.conftest import USER_ID, AuthFakes, RecordingRequestScopes
from tests.auth_fakes import a_user
from tests.builders import a_project

NOW = datetime(2026, 3, 10, 9, 30, tzinfo=UTC)
TODAY = date(2026, 3, 10)


def due_in(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.fixture
def pinned_clock(request_scopes: RecordingRequestScopes) -> None:
    """The day is pinned; the seconds tick, so tasks created in a row have an order."""
    ticks = itertools.count()
    request_scopes.clock = lambda: NOW + timedelta(seconds=next(ticks))


@pytest.fixture
async def me(auth_fakes: AuthFakes) -> str:
    """``USER_ID`` as a stored, active user, so tasks can be assigned to the caller."""
    await auth_fakes.users.add(a_user(user_id=USER_ID))
    return str(USER_ID)


@pytest.fixture
async def ballast(request_scopes: RecordingRequestScopes) -> str:
    project = a_project(name="Ballast Tasks", key="BT")
    await request_scopes.tasks.projects.add(project)
    return str(project.id)


async def create(client: httpx.AsyncClient, **body: object) -> dict[str, object]:
    response = await client.post("/tasks", json={"title": "Write the report"} | body)
    assert response.status_code == 201, response.text
    created: dict[str, object] = response.json()
    return created


async def listed(client: httpx.AsyncClient, query: str = "") -> list[str]:
    response = await client.get(f"/tasks{query}")
    assert response.status_code == 200, response.text
    return [task["title"] for task in response.json()["items"]]


def invalid(kind: str, loc: list[str], msg: str) -> dict[str, object]:
    return {"detail": [{"type": kind, "loc": loc, "msg": msg}]}


# --- POST /tasks ---------------------------------------------------------------------------


async def test_a_task_without_a_project_lands_in_the_inbox_with_the_design_defaults(
    task_client: httpx.AsyncClient,
) -> None:
    first = await create(task_client)
    second = await create(task_client)

    TaskResponse.model_validate(first)
    assert first["project_id"] == str(DEFAULT_PROJECT_ID)
    assert (first["key"], second["key"]) == ("IN-01", "IN-02")
    assert (first["priority"], first["importance"], first["status"]) == ("P2", 50, "todo")


async def test_a_task_takes_its_key_from_its_project_and_keeps_what_the_board_sent(
    task_client: httpx.AsyncClient, ballast: str
) -> None:
    body = await create(
        task_client, project_id=ballast, status="testing", priority="P0", importance=95
    )

    assert (body["project_id"], body["key"]) == (ballast, "BT-01")
    assert (body["status"], body["priority"], body["importance"]) == ("testing", "P0", 95)
    assert body["completed_at"] is None


async def test_a_task_created_in_the_done_column_is_completed(
    task_client: httpx.AsyncClient,
) -> None:
    body = await create(task_client, status="done")

    assert body["completed_at"] == body["created_at"]


async def test_create_refuses_a_project_that_does_not_exist(
    task_client: httpx.AsyncClient, request_scopes: RecordingRequestScopes
) -> None:
    response = await task_client.post(
        "/tasks", json={"title": "t", "project_id": str(uuid.uuid4())}
    )

    assert response.status_code == 422
    assert response.json() == invalid(
        "unknown_project",
        ["body", "project_id"],
        "project_id must be the id of an existing project",
    )
    assert request_scopes.tasks.all() == []
    assert request_scopes.events[-1] == "rollback"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"priority": "P4"}, id="priority outside P0-P3"),
        pytest.param({"priority": 0}, id="priority as a number"),
        pytest.param({"importance": 101}, id="importance above 100"),
        pytest.param({"importance": -1}, id="importance below 0"),
        pytest.param({"importance": 50.5}, id="importance not whole"),
        pytest.param({"importance": None}, id="importance null"),
        pytest.param({"status": "blocked"}, id="unknown status"),
        pytest.param({"project_id": "not-a-uuid"}, id="project id not a uuid"),
        pytest.param({"key": "BT-99"}, id="key is never the caller's to choose"),
    ],
)
async def test_create_rejects_an_invalid_body(
    task_client: httpx.AsyncClient, body: dict[str, object]
) -> None:
    response = await task_client.post("/tasks", json={"title": "t"} | body)

    assert response.status_code == 422
    assert "input" not in response.json()["detail"][0]


# --- GET, PATCH, DELETE /tasks/{id_or_key} ---------------------------------------------------


@pytest.mark.parametrize("reference", ["IN-01", "in-1", "In-001"])
async def test_a_task_is_found_by_its_key_in_any_case_and_padding(
    task_client: httpx.AsyncClient, reference: str
) -> None:
    created = await create(task_client)

    response = await task_client.get(f"/tasks/{reference}")

    assert response.status_code == 200
    assert response.json() == created


async def test_an_unknown_key_is_404_and_a_malformed_reference_is_422(
    task_client: httpx.AsyncClient,
) -> None:
    unknown = await task_client.get("/tasks/IN-99")
    malformed = await task_client.get("/tasks/not-a-task")

    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Task IN-99 not found"}
    assert malformed.status_code == 422
    assert malformed.json() == invalid(
        "invalid_task_reference",
        ["path", "id_or_key"],
        "must be a task id (UUID) or a task key such as BT-04",
    )


async def test_a_task_is_changed_and_deleted_by_its_key(task_client: httpx.AsyncClient) -> None:
    created = await create(task_client)

    patched = await task_client.patch("/tasks/IN-01", json={"status": "done"})
    deleted = await task_client.delete("/tasks/in-1")

    assert patched.status_code == 200
    assert (patched.json()["id"], patched.json()["status"]) == (created["id"], "done")
    assert deleted.status_code == 204
    assert (await task_client.get(f"/tasks/{created['id']}")).status_code == 404
    assert (await task_client.patch("/tasks/IN-01", json={"title": "x"})).status_code == 404
    assert (await task_client.delete("/tasks/IN-01")).status_code == 404


async def test_patch_changes_priority_importance_and_project_and_keeps_the_key(
    task_client: httpx.AsyncClient, ballast: str
) -> None:
    created = await create(task_client)

    response = await task_client.patch(
        f"/tasks/{created['id']}",
        json={"priority": "P0", "importance": 95, "project_id": ballast, "status": "testing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["priority"], body["importance"], body["project_id"]) == ("P0", 95, ballast)
    assert (body["key"], body["status"], body["completed_at"]) == ("IN-01", "testing", None)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"priority": None}, id="priority null"),
        pytest.param({"importance": None}, id="importance null"),
        pytest.param({"project_id": None}, id="project null"),
        pytest.param({"importance": 101}, id="importance above 100"),
        pytest.param({"key": "BT-99"}, id="the key never changes"),
    ],
)
async def test_patch_rejects_an_invalid_body_and_leaves_the_task_alone(
    task_client: httpx.AsyncClient, body: dict[str, object]
) -> None:
    created = await create(task_client)

    response = await task_client.patch(f"/tasks/{created['id']}", json=body)

    assert response.status_code == 422
    assert (await task_client.get(f"/tasks/{created['id']}")).json() == created


async def test_patch_refuses_a_move_to_a_project_that_does_not_exist(
    task_client: httpx.AsyncClient,
) -> None:
    created = await create(task_client)

    response = await task_client.patch(
        f"/tasks/{created['id']}", json={"project_id": str(uuid.uuid4())}
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "unknown_project"
    assert (await task_client.get(f"/tasks/{created['id']}")).json() == created


# --- attention -----------------------------------------------------------------------------


@pytest.mark.usefixtures("pinned_clock")
async def test_every_task_carries_what_asks_for_attention_today(
    task_client: httpx.AsyncClient, me: str
) -> None:
    calm = await create(task_client, due_date=due_in(30), assignee_id=me)
    late = await create(task_client, due_date=due_in(-3))
    at_risk = await create(task_client, due_date=due_in(4), priority="P0", assignee_id=me)

    assert calm["attention"] == {
        "is_overdue": False,
        "is_due_soon": False,
        "is_p0_at_risk": False,
        "needs_owner": False,
        "days_until_due": 30,
        "urgency": 58.0,
        "reasons": [],
    }
    assert late["attention"] == {
        "is_overdue": True,
        "is_due_soon": False,
        "is_p0_at_risk": False,
        "needs_owner": True,
        "days_until_due": -3,
        "urgency": 1030 + 40 + 5 + 3,
        "reasons": ["overdue", "needs_owner"],
    }
    assert at_risk["attention"]["reasons"] == ["p0_at_risk", "due_soon"]
    assert at_risk["attention"]["is_due_soon"] is True
    listed_late = (await task_client.get("/tasks?scope=overdue")).json()["items"][0]
    assert listed_late["attention"] == late["attention"]
    assert (await task_client.get(f"/tasks/{late['id']}")).json()["attention"] == late["attention"]


async def test_attention_follows_the_clock_not_the_day_the_task_was_written(
    task_client: httpx.AsyncClient, request_scopes: RecordingRequestScopes
) -> None:
    request_scopes.clock = lambda: NOW
    created = await create(task_client, due_date=due_in(1))
    request_scopes.clock = lambda: NOW + timedelta(days=2)

    later = (await task_client.get(f"/tasks/{created['id']}")).json()

    assert created["attention"]["days_until_due"] == 1
    assert (later["attention"]["days_until_due"], later["attention"]["is_overdue"]) == (-1, True)


# --- GET /tasks: filters, sorts, pages -------------------------------------------------------


@pytest.fixture
async def workspace(
    task_client: httpx.AsyncClient,
    auth_fakes: AuthFakes,
    pinned_clock: None,
    me: str,
    ballast: str,
) -> dict[str, str]:
    lucia = a_user()
    await auth_fakes.users.add(lucia)
    await create(
        task_client,
        title="late",
        project_id=ballast,
        due_date=due_in(-3),
        assignee_id=me,
        priority="P1",
        importance=80,
        description="FastAPI routes",
    )
    await create(
        task_client,
        title="p0",
        project_id=ballast,
        due_date=due_in(1),
        priority="P0",
        importance=95,
    )
    await create(
        task_client, title="today", status="testing", due_date=due_in(0), assignee_id=str(lucia.id)
    )
    await create(task_client, title="undated", description="needs the API")
    await create(task_client, title="shipped", status="done", due_date=due_in(-5), assignee_id=me)
    return {"me": me, "lucia": str(lucia.id), "ballast": ballast}


async def test_the_default_list_is_the_open_tasks_most_urgent_first(
    task_client: httpx.AsyncClient, workspace: dict[str, str]
) -> None:
    response = await task_client.get("/tasks")

    body = response.json()
    TaskListResponse.model_validate(body)
    assert [task["title"] for task in body["items"]] == ["late", "p0", "today", "undated"]
    assert (body["total"], body["limit"], body["offset"]) == (4, 50, 0)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?status=all", ["late", "p0", "today", "undated", "shipped"]),
        ("?status=open", ["late", "p0", "today", "undated"]),
        ("?status=done", ["shipped"]),
        ("?status=testing&status=done", ["today", "shipped"]),
        ("?scope=mine", ["late"]),
        ("?scope=mine&status=all", ["late", "shipped"]),
        ("?scope=overdue", ["late"]),
        ("?due=overdue&status=all", ["late"]),
        ("?due=today", ["today"]),
        ("?due=week", ["p0", "today"]),
        ("?due=none", ["undated"]),
        (f"?due_before={due_in(0)}&status=all", ["late", "today", "shipped"]),
        (f"?due_after={due_in(0)}", ["p0", "today"]),
        ("?priority=P0", ["p0"]),
        ("?priority=P0&priority=P1", ["late", "p0"]),
        ("?assignee_id=unassigned", ["p0", "undated"]),
        ("?q=api", ["late", "undated"]),
        ("?q=%20%20API%20", ["late", "undated"]),
        ("?q=%20", ["late", "p0", "today", "undated"]),
        ("?signal=overdue", ["late"]),
        ("?signal=p0_at_risk", ["p0"]),
        ("?signal=due_soon", ["p0", "today"]),
        ("?signal=needs_owner", ["p0", "undated"]),
        ("?sort=importance", ["p0", "late", "undated", "today"]),
        ("?sort=due_date", ["late", "today", "p0", "undated"]),
        ("?sort=updated", ["undated", "today", "p0", "late"]),
        ("?limit=2", ["late", "p0"]),
        ("?limit=2&offset=2", ["today", "undated"]),
        ("?offset=9", []),
    ],
)
async def test_list_parameters(
    task_client: httpx.AsyncClient, workspace: dict[str, str], query: str, expected: list[str]
) -> None:
    assert await listed(task_client, query) == expected


async def test_list_filters_by_project_and_by_assignee(
    task_client: httpx.AsyncClient, workspace: dict[str, str]
) -> None:
    assert await listed(task_client, f"?project_id={workspace['ballast']}") == ["late", "p0"]
    assert await listed(task_client, f"?assignee_id={workspace['lucia']}") == ["today"]
    assert await listed(task_client, f"?project_id={uuid.uuid4()}") == []


async def test_a_page_reports_the_total_and_echoes_limit_and_offset(
    task_client: httpx.AsyncClient, workspace: dict[str, str]
) -> None:
    body = (await task_client.get("/tasks?limit=1&offset=3&status=all")).json()

    assert [task["title"] for task in body["items"]] == ["undated"]
    assert (body["total"], body["limit"], body["offset"]) == (5, 1, 3)


@pytest.mark.parametrize(
    "query",
    [
        "?limit=0",
        "?limit=201",
        "?limit=ten",
        "?offset=-1",
        "?scope=theirs",
        "?status=blocked",
        "?status=open&status=done",
        "?status=all&status=todo",
        "?due=tomorrow",
        "?due_before=10-03-2026",
        f"?due_after={due_in(2)}&due_before={due_in(1)}",
        "?priority=P4",
        "?assignee_id=nobody",
        "?project_id=inbox",
        "?signal=blinking",
        "?sort=title",
        f"?q={'x' * 201}",
        "?page=2",
    ],
)
async def test_list_rejects_parameters_it_does_not_understand(
    task_client: httpx.AsyncClient, query: str
) -> None:
    response = await task_client.get(f"/tasks{query}")

    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["loc"][0] == "query"
    assert "input" not in detail


async def test_the_limit_accepts_its_bounds(task_client: httpx.AsyncClient) -> None:
    assert (await task_client.get("/tasks?limit=1")).status_code == 200
    assert (await task_client.get("/tasks?limit=200")).json()["limit"] == 200


# --- GET /tasks/summary ------------------------------------------------------------------------


async def test_the_summary_hydrates_the_sidebar_and_the_attention_strip(
    task_client: httpx.AsyncClient, workspace: dict[str, str]
) -> None:
    response = await task_client.get("/tasks/summary")

    assert response.status_code == 200
    body = response.json()
    TaskSummaryResponse.model_validate(body)
    assert body["counts"] == {"all": 4, "mine": 1, "overdue": 1}
    assert [(p["key"], p["name"], p["open_tasks"]) for p in body["projects"]] == [
        ("BT", "Ballast Tasks", 2),
        ("IN", "Inbox", 2),
    ]
    assert body["signals"] == {"overdue": 1, "p0_at_risk": 1, "due_soon": 2, "needs_owner": 2}


async def test_the_strip_follows_the_filters_and_the_sidebar_does_not(
    task_client: httpx.AsyncClient, workspace: dict[str, str]
) -> None:
    in_inbox = (await task_client.get(f"/tasks/summary?project_id={DEFAULT_PROJECT_ID}")).json()
    chip_chosen = (await task_client.get("/tasks/summary?signal=overdue&status=done")).json()

    assert in_inbox["signals"] == {"overdue": 0, "p0_at_risk": 0, "due_soon": 1, "needs_owner": 1}
    assert in_inbox["counts"] == {"all": 4, "mine": 1, "overdue": 1}
    assert chip_chosen["signals"] == {
        "overdue": 1,
        "p0_at_risk": 1,
        "due_soon": 2,
        "needs_owner": 2,
    }


async def test_the_summary_of_an_empty_workspace_is_all_zeroes(
    task_client: httpx.AsyncClient,
) -> None:
    body = (await task_client.get("/tasks/summary")).json()

    assert body["counts"] == {"all": 0, "mine": 0, "overdue": 0}
    assert body["signals"] == {"overdue": 0, "p0_at_risk": 0, "due_soon": 0, "needs_owner": 0}
    assert [(p["key"], p["open_tasks"]) for p in body["projects"]] == [("IN", 0)]


@pytest.mark.parametrize("query", ["?sort=urgency", "?limit=5", "?offset=1", "?status=blocked"])
async def test_the_summary_takes_filters_only(task_client: httpx.AsyncClient, query: str) -> None:
    assert (await task_client.get(f"/tasks/summary{query}")).status_code == 422


async def test_summary_is_not_mistaken_for_a_task_reference(
    task_client: httpx.AsyncClient,
) -> None:
    assert (await task_client.get("/tasks/summary")).status_code == 200


@pytest.mark.parametrize("path", ["/tasks/summary", "/tasks/IN-01", "/tasks?status=all"])
async def test_the_new_task_routes_need_a_signed_in_user(
    anonymous_client: httpx.AsyncClient, path: str
) -> None:
    response = await anonymous_client.get(path)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
