"""The Attachment entity: what a link may be, what a name may be, and which fields go together."""

import uuid
from datetime import UTC, datetime

import pytest
from app.domain.file_type import FileType, sniff

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


# --- files ------------------------------------------------------------------------------------

PDF_TYPE = sniff(b"%PDF-1.7\n....")
PNG_TYPE = sniff(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
assert PDF_TYPE is not None
assert PNG_TYPE is not None


def a_stored_file(file_name: str | None, file_type: FileType = PDF_TYPE) -> Attachment:
    return Attachment.file(
        attachment_id=uuid.uuid4(),
        task_id=TASK_ID,
        file_name=file_name,
        file_type=file_type,
        storage_key="0123456789abcdef0123456789abcdef",
        size_bytes=2048,
        created_by=USER_ID,
        now=NOW,
    )


def test_a_file_takes_its_kind_and_content_type_from_what_the_bytes_said() -> None:
    pdf, image = a_stored_file("report.pdf"), a_stored_file("shot.png", PNG_TYPE)

    assert (pdf.kind, pdf.content_type, pdf.name) == (
        AttachmentKind.PDF,
        "application/pdf",
        "report.pdf",
    )
    assert (image.kind, image.content_type, image.name) == (
        AttachmentKind.IMAGE,
        "image/png",
        "shot.png",
    )
    assert (pdf.storage_key, pdf.size_bytes, pdf.url) == (
        "0123456789abcdef0123456789abcdef",
        2048,
        None,
    )


@pytest.mark.parametrize(
    ("file_name", "name"),
    [
        ("report.pdf", "report.pdf"),
        ("REPORT.PDF", "REPORT.PDF"),
        ("  spaced   out  .pdf ", "spaced out .pdf"),
        ("../../etc/passwd", "passwd.pdf"),
        ("..\\..\\windows\\system32\\evil.pdf", "evil.pdf"),
        ("C:\\Users\\ada\\report.pdf", "report.pdf"),
        ("/etc/cron.d/job.pdf", "job.pdf"),
        ("..", "file.pdf"),
        (".", "file.pdf"),
        ("", "file.pdf"),
        ("   ", "file.pdf"),
        (None, "file.pdf"),
        (".htaccess", "htaccess.pdf"),
        ("...hidden.pdf", "hidden.pdf"),
        ("trailing.pdf...", "trailing.pdf"),
        ("nul\x00byte.pdf", "nulbyte.pdf"),
        ("line\r\nbreak.pdf", "linebreak.pdf"),
        ("tab\there.pdf", "tabhere.pdf"),
        ("invoice\u202efdp.exe", "invoicefdp.exe.pdf"),
        ("evil.exe", "evil.exe.pdf"),
        ("page.html", "page.html.pdf"),
        ("no-extension", "no-extension.pdf"),
        ('quo"te;.pdf', 'quo"te;.pdf'),
        ("r\u00e9sum\u00e9 \u2013 final.pdf", "r\u00e9sum\u00e9 \u2013 final.pdf"),
    ],
)
def test_a_file_name_is_display_metadata_sanitised_and_honest_about_the_type(
    file_name: str | None, name: str
) -> None:
    assert a_stored_file(file_name).name == name


def test_a_name_that_claims_another_type_gets_the_extension_of_what_the_file_is() -> None:
    assert a_stored_file("report.pdf", PNG_TYPE).name == "report.pdf.png"
    assert a_stored_file("photo.JPEG", sniff(b"\xff\xd8\xff\xe0")).name == "photo.JPEG"  # type: ignore[arg-type]


def test_a_long_file_name_is_cut_to_the_limit_and_keeps_its_extension() -> None:
    name = a_stored_file("x" * 400 + ".pdf").name

    assert len(name) == NAME_MAX_LENGTH
    assert name.endswith("x.pdf")
    assert a_stored_file("y" * 400).name == "y" * (NAME_MAX_LENGTH - 4) + ".pdf"


@pytest.mark.parametrize(
    "overrides",
    [
        {"content_type": "text/html"},
        {"content_type": "image/svg+xml"},
        {"kind": AttachmentKind.IMAGE},
        {"kind": AttachmentKind.PDF, "content_type": "image/png"},
        {"storage_key": "../outside"},
        {"storage_key": "/etc/passwd"},
        {"storage_key": ""},
    ],
)
def test_a_stored_file_of_a_type_or_under_a_key_the_server_would_never_write_is_refused(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(InvalidAttachmentError):
        stored(**overrides)
