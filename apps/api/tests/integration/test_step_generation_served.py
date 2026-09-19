"""Real TCP -> Redis -> real Celery worker -> PostgreSQL -> poll, completely offline.

Use -s to retain the redacted task-feature transcript. Auth credentials are never printed.
All spawned processes are private to this fixture and are reaped in its finally block.
"""

import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from tests.api.test_rate_limit_served import (
    API_ROOT,
    _free_port,
    _image_command,
    _on_loopback,
    _wait_until_serving,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def generation_server(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[str, Callable[[], None]]]:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("AI__PROVIDER", "fake")
    monkeypatch.setenv("AI__TIMEOUT_SECONDS", "1")
    monkeypatch.delenv("AI__API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT__AUTHENTICATED__LIMIT", "300")
    monkeypatch.setenv("RATE_LIMIT__AUTHENTICATED__WINDOW_SECONDS", "600")
    port = _free_port()
    processes: list[subprocess.Popen[bytes]] = []
    with (tmp_path / "generation-processes.log").open("wb") as log:
        server = subprocess.Popen(  # noqa: S603 (repository-owned argv)
            _on_loopback(_image_command(), port), cwd=API_ROOT, stdout=log, stderr=log
        )
        processes.append(server)

        def start_worker() -> None:
            worker = subprocess.Popen(  # noqa: S603 (repository-owned argv)
                [
                    sys.executable,
                    "-m",
                    "celery",
                    "-A",
                    "tests.generation_worker",
                    "worker",
                    "--pool=solo",
                    "--concurrency=1",
                    "--without-gossip",
                    "--without-mingle",
                    "--without-heartbeat",
                    "--loglevel=INFO",
                    f"--hostname=generation-{uuid4().hex}@test",
                ],
                cwd=API_ROOT,
                stdout=log,
                stderr=log,
            )
            processes.append(worker)

        try:
            url = f"http://127.0.0.1:{port}"
            _wait_until_serving(server, url)
            yield url, start_worker
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def test_queued_generation_lifecycle_and_safe_failures(
    generation_server: tuple[str, Callable[[], None]],
) -> None:
    url, start_worker = generation_server
    with httpx.Client(base_url=url, timeout=10) as client:
        email = f"{uuid4().hex}@example.com"
        registered = client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "correct horse battery",
                "full_name": "Draft Tester",
            },
        )
        assert registered.status_code == 201, registered.text
        login = client.post(
            "/auth/login", data={"username": email, "password": "correct horse battery"}
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        def request(
            method: str,
            path: str,
            expected: int = 200,
            body: dict[str, object] | None = None,
            *,
            anonymous: bool = False,
        ) -> Any:
            response = client.request(method, path, json=body, headers={} if anonymous else headers)
            print(f"\n{method} {path} -> HTTP {response.status_code} {response.text}")  # noqa: T201
            assert response.status_code == expected, response.text
            assert "PRIVATE-PROVIDER-SECRET" not in response.text
            return response.json() if response.content else None

        def new_task(title: str) -> str:
            return str(
                request(
                    "POST", "/tasks", 201, {"title": title, "description": "Read this description"}
                )["id"]
            )

        def start(task: str) -> str:
            result = request("POST", f"/tasks/{task}/step-generations", 202)
            assert result["state"] == "pending"
            assert result["titles"] == []
            return f"/tasks/{task}/step-generations/{result['id']}"

        seen_states: set[str] = set()

        def poll(path: str) -> dict[str, Any]:
            deadline = time.monotonic() + 25
            states = []
            while time.monotonic() < deadline:
                result: dict[str, Any] = request("GET", path)
                states.append(result["state"])
                seen_states.add(result["state"])
                if result["state"] in {"success", "failure"}:
                    assert set(states) <= {"pending", "running", "success", "failure"}
                    return result
                assert result["titles"] == []
                time.sleep(0.05)
            pytest.fail("real worker did not produce a terminal result")

        task = new_task("context")
        request("POST", f"/tasks/{task}/steps", 201, {"title": "Already stored"})
        before = request("GET", f"/tasks/{task}")
        activity_before = request("GET", f"/tasks/{task}/activity")
        started_at = time.monotonic()
        path = start(task)
        assert time.monotonic() - started_at < 2  # no worker yet: publication, not generation
        assert request("GET", path)["state"] == "pending"
        other = new_task("another task")
        other_path = start(other)
        again_path = start(task)
        deleted = new_task("deleted while queued")
        deleted_path = start(deleted)
        request("DELETE", f"/tasks/{deleted}", 204)
        request("GET", deleted_path, 404)
        request("POST", f"/tasks/{uuid4()}/step-generations", 404)
        request("GET", f"/tasks/{task}/step-generations/{uuid4()}", 404)
        request("GET", path.replace(task, other), 404)
        request("POST", f"/tasks/{task}/step-generations", 401, anonymous=True)
        request("GET", path, 401, anonymous=True)
        request("GET", f"/tasks/{task}/step-generations/not-a-uuid", 422)

        start_worker()
        result = poll(path)
        assert result["state"] == "success"
        assert result["titles"] == ["Read this description", "Already stored"]
        assert poll(other_path)["state"] == "success"
        assert poll(again_path)["titles"] == result["titles"]
        assert request("GET", f"/tasks/{task}") == before
        assert request("GET", f"/tasks/{task}/activity") == activity_before
        # Selecting another task does not consume or replace the first task's result.
        assert request("GET", path) == result
        for title, error in [
            ("empty", "invalid_output"),
            ("malformed", "invalid_output"),
            ("oversized", "invalid_output"),
            ("invalid_unicode", "invalid_output"),
            ("too_many", "invalid_output"),
            ("provider_error", "provider_unavailable"),
            ("timeout", "timeout"),
        ]:
            failing_task = new_task(title)
            feed = request("GET", f"/tasks/{failing_task}/activity")
            failure_path = start(failing_task)
            failure = poll(failure_path)
            assert failure["state"] == "failure"
            assert failure["titles"] == []
            assert failure["error"] == error
            assert request("GET", f"/tasks/{failing_task}/steps") == {"items": []}
            assert request("GET", f"/tasks/{failing_task}/activity") == feed
            if title == "provider_error":
                request("PATCH", f"/tasks/{failing_task}", 200, {"title": "retry recovered"})
                assert poll(start(failing_task))["state"] == "success"
                assert request("GET", failure_path) == failure
        assert "running" in seen_states
        accepted = request(
            "POST", f"/tasks/{task}/steps/bulk", 201, {"titles": result["titles"][:1]}
        )
        assert len(accepted["items"]) == 1
        assert len(request("GET", f"/tasks/{task}/steps")["items"]) == 2
