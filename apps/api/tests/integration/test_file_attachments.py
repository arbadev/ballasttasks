"""Real TCP HTTP, PostgreSQL, Redis and disk; no auth or storage doubles."""

import asyncio
import socket
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bootstrap import Container, build_container, load_settings
from app.infrastructure.db.models.attachment import AttachmentModel
from app.main import create_app
from tests.fakes import UploadedFile
from tests.integration.test_tasks_api import register_and_log_in

pytestmark = pytest.mark.integration
PDF = b"%PDF-1.7\n" + b"x" * 100


@pytest.fixture
async def container(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[Container]:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("STORAGE__LOCAL_DIRECTORY", str(tmp_path / "attachments"))
    monkeypatch.setenv("STORAGE__MAX_BYTES", "1024")
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


async def test_live_http_attachments_lifecycle_and_failures(
    http: httpx.AsyncClient, container: Container
) -> None:
    user = await register_and_log_in(http, "Attachment tester")
    task = (await http.post("/tasks", json={"title": "Attachments"}, headers=user.headers)).json()
    path = f"/tasks/{task['key']}/attachments"
    link = await http.post(
        path + "/links", json={"url": "https://example.com"}, headers=user.headers
    )
    assert link.status_code == 201
    for url in (
        "javascript:alert(1)",
        "data:text/html,x",
        "file:///etc/passwd",
        "/relative",
        "https://user:secret@example.com",
        "https://example.com/" + "x" * 2000,
    ):
        rejected = await http.post(path + "/links", json={"url": url}, headers=user.headers)
        assert rejected.status_code == 422
    response = await http.post(
        path + "/files",
        files={"file": ("../../report.pdf", PDF, "image/png")},
        headers=user.headers,
    )
    assert response.status_code == 201, response.text
    file = response.json()
    content_path = path + f"/{file['id']}/content"
    content = await http.get(content_path, headers=user.headers)
    assert content.status_code == 200
    assert content.content == PDF
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.headers["content-type"] == "application/pdf"
    assert content.headers["content-disposition"].startswith("attachment;")
    assert (await http.get(content_path)).status_code == 401
    for data, code in ((b"", 422), (b"<svg/>", 415), (b"%PD", 415), (PDF * 100, 413)):
        refused = await http.post(
            path + "/files", files={"file": ("report.pdf", data)}, headers=user.headers
        )
        assert refused.status_code == code, refused.text
        assert "detail" in refused.json()
    assert (
        await http.post(
            f"/tasks/{uuid.uuid4()}/attachments/files",
            files={"file": ("a.pdf", PDF)},
            headers=user.headers,
        )
    ).status_code == 404
    detail = (await http.get(f"/tasks/{task['id']}", headers=user.headers)).json()
    assert detail["attachments_count"] == 2
    assert len(detail["attachments"]) == 2
    assert (
        await http.delete(path + f"/{link.json()['id']}", headers=user.headers)
    ).status_code == 204
    assert (await http.delete(path + f"/{file['id']}", headers=user.headers)).status_code == 204
    assert (await http.get(content_path, headers=user.headers)).status_code == 404
    again = await http.post(path + "/files", files={"file": ("a.pdf", PDF)}, headers=user.headers)
    assert again.status_code == 201
    assert (await http.delete(f"/tasks/{task['id']}", headers=user.headers)).status_code == 204
    assert not list(container.settings.storage.local_directory.rglob("*.pdf"))
    assert not [p for p in container.settings.storage.local_directory.rglob("*") if p.is_file()]


async def test_database_failure_after_file_write_compensates_storage(container: Container) -> None:
    async with container.request_scope() as scope:
        user = await scope.register_user.execute(
            email=f"{uuid.uuid4().hex}@example.com",
            full_name="Tester",
            password="correct horse battery",
        )
        task = await scope.create_task.execute(title="Rollback", created_by=user.id)
    with pytest.raises(IntegrityError):
        await container.attach_file.execute(
            task.id, file=UploadedFile(PDF, name="a.pdf"), created_by=uuid.uuid4()
        )
    assert not [p for p in container.settings.storage.local_directory.rglob("*") if p.is_file()]
    async with container.request_scope() as scope:
        assert await scope.attachments.list_for_task(task.id) == []
        await scope.delete_task.execute(task.id)


async def test_commit_failure_after_file_write_compensates_storage(container: Container) -> None:
    async with container.request_scope() as scope:
        user = await scope.register_user.execute(
            email=f"{uuid.uuid4().hex}@example.com",
            full_name="Tester",
            password="correct horse battery",
        )
        task = await scope.create_task.execute(title="Commit rollback", created_by=user.id)

    def refuse_commit(session: Session) -> None:
        """Refuse the commit of the unit of work that stores the row, not the one that
        checked the task before the file was written."""
        if not session.in_nested_transaction() and any(
            isinstance(instance, AttachmentModel) for instance in session
        ):
            raise RuntimeError("commit failed")

    event.listen(Session, "before_commit", refuse_commit)
    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            await container.attach_file.execute(
                task.id, file=UploadedFile(PDF, name="a.pdf"), created_by=user.id
            )
    finally:
        event.remove(Session, "before_commit", refuse_commit)
    assert not [p for p in container.settings.storage.local_directory.rglob("*") if p.is_file()]
    async with container.request_scope() as scope:
        assert await scope.attachments.list_for_task(task.id) == []
        await scope.delete_task.execute(task.id)
