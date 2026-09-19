"""The Attachment entity: what a link may be, what a name may be, and which fields go together."""

import uuid
from datetime import UTC, datetime

import pytest
from app.domain.attachment import (
    NAME_MAX_LENGTH,
    URL_MAX_LENGTH,
    Attachment,
    AttachmentKind,
    InvalidAttachmentError,
)

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
TASK_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def a_link(url: str, name: str | None = None) -> Attachment:
    return Attachment.link(
        attachment_id=uuid.uuid4(),
        task_id=TASK_ID,
        url=url,
        name=name,
        created_by=USER_ID,
        now=NOW,
    )


def test_a_link_keeps_its_url_as_given_and_has_no_file_fields() -> None:
    link = a_link("https://github.com/arbadev/ballasttasks?tab=readme#ports", "The repository")

    assert link.kind is AttachmentKind.LINK
    assert link.url == "https://github.com/arbadev/ballasttasks?tab=readme#ports"
    assert link.name == "The repository"
    assert (link.task_id, link.created_by, link.created_at) == (TASK_ID, USER_ID, NOW)
    assert (link.storage_key, link.content_type, link.size_bytes) == (None, None, None)


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://github.com/arbadev/ballasttasks", "github.com"),
        ("http://localhost:8000/docs", "localhost:8000"),
        ("HTTPS://Example.COM/Path", "example.com"),
        ("https://[2001:db8::1]:8443/x", "[2001:db8::1]:8443"),
        ("https://xn--bcher-kva.example/", "xn--bcher-kva.example"),
    ],
)
@pytest.mark.parametrize("name", [None, "", "   "])
def test_a_link_without_a_name_is_named_after_its_host(
    url: str, host: str, name: str | None
) -> None:
    assert a_link(url, name).name == host


def test_the_surrounding_whitespace_of_a_url_and_a_name_is_dropped() -> None:
    link = a_link("  https://example.com/a  ", "  Swagger UI  ")

    assert (link.url, link.name) == ("https://example.com/a", "Swagger UI")


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://example.com/file",
        "mailto:ada@example.com",
        "vbscript:msgbox(1)",
        "/relative/path",
        "relative/path",
        "../up",
        "//example.com/scheme-relative",
        "example.com",
        "http://",
        "http:///no-host",
        "http:example.com",
        "http:\\\\example.com",
        "https://user:secret@example.com/",
        "https://user@example.com/",
        "https://@example.com/",
        "https://example.com:99999/",
        "https://example.com:port/",
        "https://exa mple.com/",
        "https://example.com/a b",
        "https://example.com/\nX-Injected: 1",
        "https://example.com/\x00",
        "https://example.com/\u202e",
        "https://[::1/",
        "",
        "   ",
    ],
)
def test_anything_but_an_absolute_http_url_without_credentials_is_refused(url: str) -> None:
    with pytest.raises(InvalidAttachmentError):
        a_link(url)


def test_a_url_may_be_2000_characters_and_not_one_more() -> None:
    prefix = "https://example.com/"
    longest = prefix + "a" * (URL_MAX_LENGTH - len(prefix))

    assert a_link(longest).url == longest
    with pytest.raises(InvalidAttachmentError, match="2000"):
        a_link(longest + "a")


@pytest.mark.parametrize("name", ["x" * (NAME_MAX_LENGTH + 1), "tab\there", "nul\x00", "rtl\u202e"])
def test_a_name_that_is_too_long_or_hides_a_character_is_refused(name: str) -> None:
    with pytest.raises(InvalidAttachmentError):
        a_link("https://example.com", name)


def stored(**overrides: object) -> Attachment:
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "task_id": TASK_ID,
        "kind": AttachmentKind.PDF,
        "name": "report.pdf",
        "created_by": USER_ID,
        "created_at": NOW,
        "url": None,
        "storage_key": "a" * 32,
        "content_type": "application/pdf",
        "size_bytes": 1024,
    }
    return Attachment(**(fields | overrides))  # type: ignore[arg-type]


def test_a_file_has_a_storage_key_a_content_type_and_a_size_and_no_url() -> None:
    file = stored()

    assert file.is_file
    assert not a_link("https://example.com").is_file


@pytest.mark.parametrize(
    "overrides",
    [
        {"url": "https://example.com"},
        {"storage_key": None},
        {"content_type": None},
        {"size_bytes": None},
        {"size_bytes": 0},
        {"size_bytes": -1},
        {"size_bytes": True},
        {"kind": AttachmentKind.LINK},
        {"kind": AttachmentKind.LINK, "url": "https://example.com"},
        {"created_at": NOW.replace(tzinfo=None)},
        {"name": " "},
    ],
)
def test_a_stored_attachment_whose_fields_do_not_go_together_is_refused(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(InvalidAttachmentError):
        stored(**overrides)
