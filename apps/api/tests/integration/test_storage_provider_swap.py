"""Swapping the file storage provider: one registry entry, nothing else changes.

The exercise says a third party (S3, Cloudinary, ...) may replace the local disk later, so
the whole attachment lifecycle must work over real HTTP against a provider the routes and
use cases know nothing about, and the local disk must stay untouched while it does.
"""

import asyncio
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.bootstrap import Container, build_container, load_settings
from app.infrastructure.storage.in_memory import InMemoryFileStorage
from app.infrastructure.storage.local_disk import LocalDiskFileStorage
from app.infrastructure.storage.registry import STORAGE_PROVIDERS
from app.main import create_app
from tests.integration.test_tasks_api import register_and_log_in

pytestmark = pytest.mark.integration

PDF = b"%PDF-1.7\n" + b"contents of a small spec" * 4


@pytest.fixture
def disk_root(tmp_path: Path) -> Path:
    return tmp_path / "attachments"


@pytest.fixture
async def container(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch, disk_root: Path
) -> AsyncIterator[Container]:
    # What adding a provider costs: one entry here. No use case, route or schema is edited.
    monkeypatch.setitem(STORAGE_PROVIDERS, "elsewhere", lambda _settings: InMemoryFileStorage())
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("STORAGE__PROVIDER", "elsewhere")
    monkeypatch.setenv("STORAGE__LOCAL_DIRECTORY", str(disk_root))
    built = build_container(load_settings())
    yield built
    await built.aclose()


@pytest.fixture
async def http(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    # OS-allocated high loopback port; never the owner's 8000.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(
            uvicorn.Config(create_app(container=container), access_log=False, log_level="error")
        )
        serving = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:  # noqa: ASYNC110 - uvicorn exposes a flag, not an event
                    await asyncio.sleep(0.01)
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{sock.getsockname()[1]}"
            ) as client:
                yield client
        finally:
            server.should_exit = True
            await serving


def stored_on_disk(root: Path) -> list[Path]:
    return [item for item in root.rglob("*") if item.is_file()] if root.exists() else []


async def test_attachments_work_through_another_provider(
    http: httpx.AsyncClient, container: Container, disk_root: Path
) -> None:
    assert not isinstance(container.file_storage, LocalDiskFileStorage)

    user = await register_and_log_in(http, "Provider tester")
    task = (await http.post("/tasks", json={"title": "Swappable"}, headers=user.headers)).json()
    path = f"/tasks/{task['key']}/attachments"

    uploaded = await http.post(
        path + "/files",
        files={"file": ("spec.pdf", PDF, "application/pdf")},
        headers=user.headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert (body["kind"], body["name"], body["size_bytes"]) == ("pdf", "spec.pdf", len(PDF))
    assert body["content_type"] == "application/pdf"

    detail = (await http.get(f"/tasks/{task['key']}", headers=user.headers)).json()
    assert [item["id"] for item in detail["attachments"]] == [body["id"]]
    assert detail["attachments_count"] == 1

    content = await http.get(path + f"/{body['id']}/content", headers=user.headers)
    assert content.status_code == 200
    assert content.content == PDF
    assert content.headers["content-disposition"] == "attachment; filename*=UTF-8''spec.pdf"

    # The bytes went to the other provider: the local disk was never written to.
    assert stored_on_disk(disk_root) == []

    removed = await http.delete(path + f"/{body['id']}", headers=user.headers)
    assert removed.status_code == 204
    gone = await http.get(path + f"/{body['id']}/content", headers=user.headers)
    assert gone.status_code == 404
    after = await http.get(f"/tasks/{task['key']}", headers=user.headers)
    assert after.json()["attachments"] == []


async def test_oversize_and_unsupported_answers_do_not_depend_on_the_provider(
    http: httpx.AsyncClient, disk_root: Path
) -> None:
    user = await register_and_log_in(http, "Provider limits")
    task = (await http.post("/tasks", json={"title": "Limits"}, headers=user.headers)).json()
    path = f"/tasks/{task['key']}/attachments/files"

    unsupported = await http.post(
        path, files={"file": ("notes.txt", b"just text", "application/pdf")}, headers=user.headers
    )
    assert unsupported.status_code == 415

    too_large = await http.post(
        path,
        files={"file": ("huge.pdf", b"%PDF-1.7\n" + b"x" * (10 * 1024 * 1024), "application/pdf")},
        headers=user.headers,
    )
    assert too_large.status_code == 413
    assert stored_on_disk(disk_root) == []
