"""The detail contract over a TCP socket, including each route's 401/404/422/429.

Run with ``-s`` for a redacted HTTP transcript: only task-feature requests are printed,
never auth requests, passwords or bearer tokens. PostgreSQL and Redis are real; the
server is private to this test and is always terminated.
"""

import json
import subprocess
import uuid
from collections.abc import Iterator

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
def served(migrated_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("RATE_LIMIT__AUTHENTICATED__LIMIT", "80")
    monkeypatch.setenv("RATE_LIMIT__AUTHENTICATED__WINDOW_SECONDS", "600")
    port = _free_port()
    server = subprocess.Popen(  # noqa: S603 (repository-owned argv)
        _on_loopback(_image_command(), port),
        cwd=API_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        url = f"http://127.0.0.1:{port}"
        _wait_until_serving(server, url)
        yield url
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


def test_all_detail_endpoints_over_tcp(served: str) -> None:
    with httpx.Client(base_url=served, timeout=10) as client:
        email = f"{uuid.uuid4().hex}@example.com"
        password = "correct horse battery"
        registered = client.post(
            "/auth/register",
            json={"email": email, "full_name": "Ada Lovelace", "password": password},
        )
        assert registered.status_code == 201
        login = client.post("/auth/login", data={"username": email, "password": password})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        def request(
            method: str,
            path: str,
            status: int,
            body: dict[str, object] | None = None,
            *,
            anonymous: bool = False,
        ) -> httpx.Response:
            response = client.request(method, path, json=body, headers={} if anonymous else headers)
            print(f"\n{method} {path} {json.dumps(body, ensure_ascii=False)}")  # noqa: T201
            print(f"HTTP {response.status_code} {response.text}")  # noqa: T201 (transcript)
            assert response.status_code == status, response.text
            return response

        task = request("POST", "/tasks", 201, {"title": "Detail TCP test"}).json()
        base = f"/tasks/{task['key']}"
        step = request("POST", f"{base}/steps", 201, {"title": " First "}).json()
        bulk = request("POST", f"{base}/steps/bulk", 201, {"titles": ["Second", "Third"]}).json()
        step_path = f"{base}/steps/{step['id']}"
        assert request("PATCH", step_path, 200, {"title": "Renamed"}).json()["title"] == "Renamed"
        assert request("PATCH", step_path, 200, {"done": True}).json()["done"] is True
        assert request("PATCH", step_path, 200, {"done": False}).json()["done"] is False
        ids = [s["id"] for s in bulk["items"]] + [step["id"]]
        ordered = request("PUT", f"{base}/steps/order", 200, {"step_ids": ids}).json()["items"]
        assert [s["id"] for s in ordered] == ids
        assert [s["position"] for s in ordered] == [0, 1, 2]
        assert len(request("GET", f"{base}/steps", 200).json()["items"]) == 3
        comment = request("POST", f"{base}/comments", 201, {"text": " Hello "}).json()
        assert comment["text"] == "Hello"
        assert comment["actor"] == {
            "id": registered.json()["id"],
            "full_name": "Ada Lovelace",
            "initials": "AL",
        }
        feed = request("GET", f"{base}/activity?limit=1&offset=0", 200).json()
        assert feed["items"] == [comment]
        assert feed["total"] == 5  # creation, add, bulk, completion, comment
        detail = request("GET", base, 200).json()
        assert (detail["steps_total"], detail["steps_done"], detail["comments_count"]) == (3, 0, 1)
        assert "email" not in json.dumps(feed)
        request("DELETE", step_path, 204)
        assert [s["position"] for s in request("GET", f"{base}/steps", 200).json()["items"]] == [
            0,
            1,
        ]

        routes: list[tuple[str, str, dict[str, object] | None]] = [
            ("GET", "/steps", None),
            ("POST", "/steps", {"title": "x"}),
            ("POST", "/steps/bulk", {"titles": ["x"]}),
            ("PUT", "/steps/order", {"step_ids": []}),
            ("PATCH", f"/steps/{step['id']}", {"done": True}),
            ("DELETE", f"/steps/{step['id']}", None),
            ("POST", "/comments", {"text": "x"}),
            ("GET", "/activity", None),
        ]
        missing = f"/tasks/{uuid.uuid4()}"
        for method, suffix, body in routes:
            request(method, base + suffix, 401, body, anonymous=True)
            request(method, missing + suffix, 404, body)
            request(method, "/tasks/not-a-reference" + suffix, 422, body)

        request("POST", f"{base}/steps", 422, {"title": "nul\u0000byte"})
        request("POST", f"{base}/steps/bulk", 422, {"titles": ["valid", " "]})
        request("POST", f"{base}/comments", 422, {"text": "nul\u0000byte"})
        request("PUT", f"{base}/steps/order", 422, {"step_ids": ids})
        request("PATCH", step_path, 404, {"done": True})
        request("GET", f"{base}/activity?limit=0", 422)
        assert request("GET", f"{base}/activity", 200).json()["total"] == 5

        # Exhaust just this caller's real Redis budget; no global keys are cleared.
        for _ in range(81):
            response = client.get(f"{base}/steps", headers=headers)
            if response.status_code == 429:
                break
            assert response.status_code == 200
        else:
            pytest.fail("the configured authenticated budget was not enforced")
        for method, suffix, body in routes:
            limited = request(method, base + suffix, 429, body)
            assert "Retry-After" in limited.headers
            assert set(limited.json()) == {"detail"}
