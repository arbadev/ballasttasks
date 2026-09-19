from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api.security import get_current_user_id
from app.application.ports.rate_limiter import RateLimitPolicy
from app.application.ports.step_generation_jobs import GenerationJobsUnavailable
from app.application.step_generation import Generation
from app.infrastructure.rate_limit.in_memory_rate_limiter import InMemoryRateLimiter
from tests.api.conftest import USER_ID, AuthFakes
from tests.auth_fakes import a_user
from tests.generation_fakes import InMemoryStepGenerationJobs


@pytest.fixture(autouse=True)
async def me(auth_fakes: AuthFakes) -> None:
    await auth_fakes.users.add(a_user(user_id=USER_ID))


@pytest.fixture
def jobs(tasks_app: FastAPI) -> InMemoryStepGenerationJobs:
    jobs = InMemoryStepGenerationJobs()
    tasks_app.state.container = replace(tasks_app.state.container, step_generation_jobs=jobs)
    return jobs


async def test_enqueue_poll_and_explicit_acceptance(
    task_client: httpx.AsyncClient, jobs: InMemoryStepGenerationJobs
) -> None:
    task = (await task_client.post("/tasks", json={"title": "Launch"})).json()
    path = f"/tasks/{task['key']}/step-generations"
    before = (await task_client.get(f"/tasks/{task['id']}/activity")).json()
    response = await task_client.post(path)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job == {
        "id": job["id"],
        "task_id": task["id"],
        "state": "pending",
        "titles": [],
        "error": None,
    }
    assert (await task_client.get(f"{path}/{job['id']}")).json() == job
    jobs.results[UUID(job["id"])] = Generation(
        UUID(job["id"]), UUID(task["id"]), "success", ("Plan", "Ship")
    )
    result = (await task_client.get(f"{path}/{job['id']}")).json()
    assert result["titles"] == ["Plan", "Ship"]
    assert (await task_client.get(f"/tasks/{task['id']}/steps")).json() == {"items": []}
    assert (await task_client.get(f"/tasks/{task['id']}/activity")).json() == before
    accepted = await task_client.post(
        f"/tasks/{task['id']}/steps/bulk", json={"titles": result["titles"]}
    )
    assert accepted.status_code == 201
    assert len(accepted.json()["items"]) == 2


async def test_unknown_jobs_wrong_task_and_deleted_task_are_not_empty_success(
    task_client: httpx.AsyncClient, jobs: InMemoryStepGenerationJobs
) -> None:
    first = (await task_client.post("/tasks", json={"title": "First"})).json()["id"]
    second = (await task_client.post("/tasks", json={"title": "Second"})).json()["id"]
    path = f"/tasks/{first}/step-generations"
    job = (await task_client.post(path)).json()["id"]
    for url in [f"{path}/{uuid4()}", f"/tasks/{second}/step-generations/{job}"]:
        assert (await task_client.get(url)).status_code == 404
    assert (await task_client.post(f"/tasks/{uuid4()}/step-generations")).status_code == 404
    await task_client.delete(f"/tasks/{first}")
    assert (await task_client.get(f"{path}/{job}")).status_code == 404
    assert len(jobs.results) == 1


async def test_regeneration_and_concurrent_tasks_keep_independent_handles(
    task_client: httpx.AsyncClient, jobs: InMemoryStepGenerationJobs
) -> None:
    handles = []
    for title in ["First", "Second"]:
        task = (await task_client.post("/tasks", json={"title": title})).json()["id"]
        for _ in range(2):
            path = f"/tasks/{task}/step-generations"
            response = await task_client.post(path)
            assert response.status_code == 202
            handles.append((path, response.json()))
    assert len({job["id"] for _, job in handles}) == 4
    for path, job in handles:
        assert (await task_client.get(f"{path}/{job['id']}")).json() == job


async def test_another_authenticated_user_can_poll_shared_workspace_jobs(
    task_client: httpx.AsyncClient, tasks_app: FastAPI, jobs: InMemoryStepGenerationJobs
) -> None:
    task = (await task_client.post("/tasks", json={"title": "Shared task"})).json()["id"]
    path = f"/tasks/{task}/step-generations"
    job = (await task_client.post(path)).json()
    other_user_id = uuid4()
    tasks_app.dependency_overrides[get_current_user_id] = lambda: other_user_id
    assert (await task_client.get(f"{path}/{job['id']}")).json() == job
    assert (await task_client.post(path)).status_code == 202


async def test_queue_outage_is_safe_503(
    task_client: httpx.AsyncClient, jobs: InMemoryStepGenerationJobs
) -> None:
    task = (await task_client.post("/tasks", json={"title": "Launch"})).json()["id"]
    jobs.error = GenerationJobsUnavailable()
    response = await task_client.post(f"/tasks/{task}/step-generations")
    assert response.status_code == 503
    assert response.json() == {"detail": "Step generation is temporarily unavailable. Try again."}


async def test_auth_and_rate_limit_before_task_lookup(
    anonymous_client: httpx.AsyncClient, tasks_app: FastAPI, jobs: InMemoryStepGenerationJobs
) -> None:
    path = f"/tasks/{uuid4()}/step-generations"
    for method, url in [("POST", path), ("GET", f"{path}/{uuid4()}")]:
        response = await anonymous_client.request(method, url)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
    container = tasks_app.state.container
    tasks_app.state.container = replace(
        container,
        rate_limiting=replace(
            container.rate_limiting,
            limiter=InMemoryRateLimiter(),
            anonymous=RateLimitPolicy("anonymous", 1, 60),
        ),
    )
    assert (await anonymous_client.post(path)).status_code == 401
    response = await anonymous_client.post(path)
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert not jobs.results
