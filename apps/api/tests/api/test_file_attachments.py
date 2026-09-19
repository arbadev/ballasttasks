"""Files over HTTP, with the same container of fakes as task routes."""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

from app.application.ports.file_storage import StoredFile
from app.infrastructure.storage.in_memory import InMemoryFileStorage
from tests.api.conftest import AuthFakes, RecordingRequestScopes
from tests.api.test_attachments import create_task
from tests.auth_fakes import a_user

PDF = b"%PDF-1.7\n" + b"x" * 91
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 92


async def test_file_roundtrip_and_removal(
    task_client: httpx.AsyncClient, request_scopes: RecordingRequestScopes
) -> None:
    task = await create_task(task_client)
    path = f"/tasks/{task['key']}/attachments"
    response = await task_client.post(
        path + "/files", files={"file": ("../../report.pdf", PDF, "text/html")}
    )
    assert response.status_code == 201, response.text
    attached = response.json()
    assert (
        attached["kind"],
        attached["name"],
        attached["content_type"],
        attached["size_bytes"],
    ) == ("pdf", "report.pdf", "application/pdf", len(PDF))
    content = await task_client.get(path + f"/{attached['id']}/content")
    assert content.status_code == 200
    assert content.content == PDF
    assert content.headers["content-type"] == "application/pdf"
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.headers["content-disposition"].startswith("attachment;")
    assert "report.pdf" in content.headers["content-disposition"]
    assert (await task_client.delete(path + f"/{attached['id']}")).status_code == 204
    assert request_scopes.storage.stored_keys() == []
    assert (await task_client.get(path + f"/{attached['id']}/content")).status_code == 404


async def test_deleting_task_removes_stored_files(
    task_client: httpx.AsyncClient, request_scopes: RecordingRequestScopes
) -> None:
    task = await create_task(task_client)
    response = await task_client.post(
        f"/tasks/{task['id']}/attachments/files", files={"file": ("evil.exe", PNG)}
    )
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "evil.exe.png"
    assert len(request_scopes.storage.stored_keys()) == 1
    assert (await task_client.delete(f"/tasks/{task['id']}")).status_code == 204
    assert request_scopes.storage.stored_keys() == []


@pytest.mark.parametrize(
    ("data", "code"), [(b"", 422), (b"<html>evil</html>", 415), (b"%PD", 415), (PDF * 11, 413)]
)
async def test_refused_upload_leaves_no_file(
    task_client: httpx.AsyncClient, request_scopes: RecordingRequestScopes, data: bytes, code: int
) -> None:
    request_scopes.max_file_bytes = 1000
    task = await create_task(task_client)
    response = await task_client.post(
        f"/tasks/{task['id']}/attachments/files",
        files={"file": ("claimed.pdf", data, "application/pdf")},
    )
    assert response.status_code == code, response.text
    assert "detail" in response.json()
    assert request_scopes.storage.stored_keys() == []
    assert request_scopes.attachments.all() == []


@pytest.mark.parametrize("body", [b"garbage", b"--boundary\r\n"])
async def test_malformed_multipart_is_422(task_client: httpx.AsyncClient, body: bytes) -> None:
    task = await create_task(task_client)
    response = await task_client.post(
        f"/tasks/{task['id']}/attachments/files",
        content=body,
        headers={"content-type": "multipart/form-data; boundary=boundary"},
    )
    assert response.status_code == 422


async def test_a_truncated_multipart_file_is_422_and_cleaned_up(
    task_client: httpx.AsyncClient,
    request_scopes: RecordingRequestScopes,
) -> None:
    task = await create_task(task_client)
    response = await task_client.post(
        f"/tasks/{task['id']}/attachments/files",
        content=b'--b\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n\r\n'
        + PDF,
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    assert response.status_code == 422
    assert request_scopes.storage.stored_keys() == []


async def test_oversize_stops_reading_the_network_stream(
    task_client: httpx.AsyncClient,
    request_scopes: RecordingRequestScopes,
) -> None:
    request_scopes.max_file_bytes = 1000
    task = await create_task(task_client)
    consumed = []

    async def network() -> AsyncIterator[bytes]:
        yield b'--b\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n\r\n'
        for index in range(100):
            consumed.append(index)
            yield PDF
        yield b"\r\n--b--\r\n"

    response = await task_client.post(
        f"/tasks/{task['id']}/attachments/files",
        content=network(),
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    assert response.status_code == 413
    assert len(consumed) <= 12
    assert request_scopes.storage.stored_keys() == []


async def test_missing_task_never_reads_upload(task_client: httpx.AsyncClient) -> None:
    async def unread() -> AsyncIterator[bytes]:
        pytest.fail("request must be rejected before reading the file")
        yield b""

    response = await task_client.post(f"/tasks/{uuid.uuid4()}/attachments/files", content=unread())
    assert response.status_code == 404


async def test_link_has_no_file(task_client: httpx.AsyncClient) -> None:
    task = await create_task(task_client)
    path = f"/tasks/{task['id']}/attachments"
    attached = (await task_client.post(path + "/links", json={"url": "https://example.com"})).json()
    response = await task_client.get(path + f"/{attached['id']}/content")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "case", ["missing-boundary", "wrong-part", "two-files", "huge-header", "epilogue"]
)
async def test_multipart_envelope_is_bounded_and_exact(
    task_client: httpx.AsyncClient,
    request_scopes: RecordingRequestScopes,
    case: str,
) -> None:
    task = await create_task(task_client)
    path = f"/tasks/{task['id']}/attachments/files"
    if case == "missing-boundary":
        response = await task_client.post(
            path, content=PDF, headers={"content-type": "multipart/form-data"}
        )
    elif case == "wrong-part":
        response = await task_client.post(path, files={"other": ("a.pdf", PDF)})
    elif case == "two-files":
        response = await task_client.post(
            path, files=[("file", ("a.pdf", PDF)), ("file", ("b.pdf", PDF))]
        )
    else:
        name = b"x" * 20_000 if case == "huge-header" else b"a.pdf"
        body = (
            b'--b\r\nContent-Disposition: form-data; name="file"; filename="'
            + name
            + b'"\r\n\r\n'
            + PDF
            + b"\r\n--b--\r\n"
        )
        if case == "epilogue":
            body += b"x" * 100_000
        response = await task_client.post(
            path, content=body, headers={"content-type": "multipart/form-data; boundary=b"}
        )
    assert response.status_code == 422
    assert request_scopes.storage.stored_keys() == []


async def test_file_openapi(task_client: httpx.AsyncClient) -> None:
    paths = (await task_client.get("/openapi.json")).json()["paths"]
    upload = paths["/tasks/{id_or_key}/attachments/files"]["post"]
    assert set(upload["responses"]) >= {"201", "401", "404", "413", "415", "422", "429"}
    assert "multipart/form-data" in upload["requestBody"]["content"]
    download = paths["/tasks/{id_or_key}/attachments/{attachment_id}/content"]["get"]
    assert set(download["responses"]) >= {"200", "401", "404", "422", "429"}


class WatchingStorage(InMemoryFileStorage):
    """The storage fake, recording how many units of work were open while it was fed."""

    def __init__(self, scopes: RecordingRequestScopes) -> None:
        super().__init__()
        self._scopes = scopes
        self.units_open_while_storing: list[int] = []

    async def save(self, key: str, chunks: AsyncIterator[bytes]) -> StoredFile:
        self.units_open_while_storing.append(self._scopes.open_units)

        async def watched() -> AsyncIterator[bytes]:
            async for chunk in chunks:
                self.units_open_while_storing.append(self._scopes.open_units)
                yield chunk

        return await super().save(key, watched())


async def test_an_upload_holds_no_unit_of_work_while_the_body_arrives(
    anonymous_client: httpx.AsyncClient,
    auth_fakes: AuthFakes,
    request_scopes: RecordingRequestScopes,
) -> None:
    """The proof for the whole request, not only the use case.

    A signed-in upload goes through the rate limiter and the bearer token seam before it
    reaches the route, and each of those used to keep the request's transaction, and so a
    pooled database connection, for as long as the client took to send its body. Here the
    caller is a real token rather than an override, so every one of those dependencies is
    exercised, and none of them may hold a unit of work while the storage is being fed.
    """
    user = a_user()
    await auth_fakes.users.add(user)
    headers = {"Authorization": f"Bearer {auth_fakes.tokens.issue(user.id)}"}
    storage = WatchingStorage(request_scopes)
    request_scopes.storage = storage
    created = await anonymous_client.post(
        "/tasks", json={"title": "Write the report"}, headers=headers
    )
    assert created.status_code == 201, created.text
    task = created.json()

    response = await anonymous_client.post(
        f"/tasks/{task['id']}/attachments/files",
        files={"file": ("report.pdf", PDF)},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    assert storage.units_open_while_storing != [], "the storage was fed at all"
    assert set(storage.units_open_while_storing) == {0}
    assert request_scopes.open_units == 0
    assert len(storage.stored_keys()) == 1
