"""Conservative signature allowlist, not a file decoder or malware scanner."""

from dataclasses import dataclass

SNIFF_BYTES = 12


@dataclass(frozen=True, slots=True)
class FileType:
    content_type: str
    extensions: tuple[str, ...]
    is_image: bool

    @property
    def extension(self) -> str:
        return self.extensions[0]


FILE_TYPES = (
    FileType("application/pdf", (".pdf",), False),
    FileType("image/png", (".png",), True),
    FileType("image/jpeg", (".jpg", ".jpeg"), True),
    FileType("image/gif", (".gif",), True),
    FileType("image/webp", (".webp",), True),
)


def sniff(head: bytes) -> FileType | None:
    for signature, index in (
        (b"%PDF-", 0),
        (b"\x89PNG\r\n\x1a\n", 1),
        (b"\xff\xd8\xff", 2),
        (b"GIF87a", 3),
        (b"GIF89a", 3),
    ):
        if head.startswith(signature):
            return FILE_TYPES[index]
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return FILE_TYPES[4]
    return None
