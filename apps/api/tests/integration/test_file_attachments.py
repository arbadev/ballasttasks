"""Real TCP HTTP, PostgreSQL, Redis and disk; no auth or storage doubles."""

import asyncio
import errno
import os
import socket
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from app.bootstrap import Container, build_container, load_settings
from app.infrastructure.db import engine as engine_module
from app.infrastructure.db.models.attachment import AttachmentModel
from app.main import create_app
from tests.fakes import UploadedFile
from tests.integration.test_tasks_api import register_and_log_in

pytestmark = pytest.mark.integration
PDF = b"%PDF-1.7\n" + b"x" * 100
UPLOAD_HEAD = (
    b'--bt\r\nContent-Disposition: form-data; name="file"; filename="slow.pdf"\r\n\r\n' + PDF
)


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

    def note_the_row(session: Session, flush_context: object) -> None:
        """The row has to be remembered while it is still pending: by commit time it is
        clean, and the session's identity map holds it only weakly."""
        if any(isinstance(instance, AttachmentModel) for instance in session.new):
            session.info["wrote_an_attachment"] = True

    def refuse_commit(session: Session) -> None:
        """Refuse the commit of the unit of work that stores the row, not the one that
        checked the task before the file was written, and not the savepoint the row is
        written in (``in_nested_transaction`` is still true while that one commits)."""
        if session.info.get("wrote_an_attachment") and not session.in_nested_transaction():
            raise RuntimeError("commit failed")

    event.listen(Session, "after_flush", note_the_row)
    event.listen(Session, "before_commit", refuse_commit)
    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            await container.attach_file.execute(
                task.id, file=UploadedFile(PDF, name="a.pdf"), created_by=user.id
            )
    finally:
        event.remove(Session, "before_commit", refuse_commit)
        event.remove(Session, "after_flush", note_the_row)
    assert not [p for p in container.settings.storage.local_directory.rglob("*") if p.is_file()]
    async with container.request_scope() as scope:
        assert await scope.attachments.list_for_task(task.id) == []
        await scope.delete_task.execute(task.id)


@pytest.fixture
def one_pooled_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Room for exactly one database connection, and no overflow.

    Whatever holds it blocks every other request; five seconds later they fail rather than
    wait out the default half minute.
    """

    def sized(url: str, **options: object) -> AsyncEngine:
        return create_async_engine(url, pool_size=1, max_overflow=0, pool_timeout=5, **options)

    monkeypatch.setattr(engine_module, "create_async_engine", sized)


async def test_a_slow_upload_leaves_the_only_connection_for_other_requests(
    one_pooled_connection: None, http: httpx.AsyncClient, container: Container
) -> None:
    """The point of the two short units of work, on a real pool.

    The client holds its body open while the API is streaming it to disk. Nothing about
    that request may occupy the pool: not the bearer token seam, not the rate limiter and
    not the route, or the ordinary request below would wait for the upload and time out.
    """
    pool = container.engine.pool
    assert isinstance(pool, QueuePool)
    assert pool.size() == 1
    user = await register_and_log_in(http, "Slow uploader")
    task = (await http.post("/tasks", json={"title": "Slow"}, headers=user.headers)).json()
    finish = asyncio.Event()

    async def body() -> AsyncIterator[bytes]:
        yield UPLOAD_HEAD
        await finish.wait()
        yield b"\r\n--bt--\r\n"

    upload = asyncio.create_task(
        http.post(
            f"/tasks/{task['key']}/attachments/files",
            content=body(),
            headers={**user.headers, "content-type": "multipart/form-data; boundary=bt"},
        )
    )
    try:
        # The file appears on disk as it is written, which is the upload mid-flight.
        async with asyncio.timeout(10):
            while not _stored_files(container):  # noqa: ASYNC110 - the disk is the signal
                await asyncio.sleep(0.01)

        ordinary = await asyncio.wait_for(
            http.get(f"/tasks/{task['id']}", headers=user.headers), timeout=10
        )

        assert ordinary.status_code == 200, ordinary.text
        assert not upload.done(), "the upload was still holding its body open"
    finally:
        finish.set()
    response = await asyncio.wait_for(upload, timeout=10)
    assert response.status_code == 201, response.text
    assert (await http.delete(f"/tasks/{task['id']}", headers=user.headers)).status_code == 204
    assert _stored_files(container) == []


def _stored_files(container: Container) -> list[Path]:
    return [p for p in container.settings.storage.local_directory.rglob("*") if p.is_file()]


async def test_an_oversize_upload_is_still_413_when_the_cleanup_fails(
    http: httpx.AsyncClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented answer survives a storage root that turns hostile mid-request.

    The body passes the limit only after the file has been created, so removing it is
    compensation, not the outcome the client asked about: its failure is logged and the
    original 413 still reaches them, orphan and all (ADR 0008).
    """
    user = await register_and_log_in(http, "Unlucky uploader")
    task = (await http.post("/tasks", json={"title": "Oversize"}, headers=user.headers)).json()
    unlink = os.unlink

    def refuse_under_the_root(path: str, *, dir_fd: int | None = None) -> None:
        if dir_fd is None:
            unlink(path)
            return
        raise OSError(errno.EIO, "Input/output error")

    async def body() -> AsyncIterator[bytes]:
        yield UPLOAD_HEAD
        for _ in range(5):
            # Separate network chunks: the limit is passed inside the storage write, not
            # in the signature loop that runs before it.
            await asyncio.sleep(0.01)
            yield b"x" * 400
        yield b"\r\n--bt--\r\n"

    monkeypatch.setattr(os, "unlink", refuse_under_the_root)

    response = await http.post(
        f"/tasks/{task['key']}/attachments/files",
        content=body(),
        headers={**user.headers, "content-type": "multipart/form-data; boundary=bt"},
    )

    assert response.status_code == 413, response.text
    assert "detail" in response.json()
    assert _stored_files(container) != [], "the compensating removal really was attempted"
    monkeypatch.undo()
    for orphan in _stored_files(container):
        orphan.unlink()
    assert (await http.delete(f"/tasks/{task['id']}", headers=user.headers)).status_code == 204
