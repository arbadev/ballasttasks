"""What a file is, decided from its leading bytes and from nothing else."""

import pytest

from app.domain.file_type import FILE_TYPES, SNIFF_BYTES, sniff

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"
GIF87 = b"GIF87a\x01\x00\x01\x00\x80\x00"
GIF89 = b"GIF89a\x01\x00\x01\x00\x80\x00"
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 "


@pytest.mark.parametrize(
    ("head", "content_type", "extension", "is_image"),
    [
        (PDF, "application/pdf", ".pdf", False),
        (PNG, "image/png", ".png", True),
        (JPEG, "image/jpeg", ".jpg", True),
        (GIF87, "image/gif", ".gif", True),
        (GIF89, "image/gif", ".gif", True),
        (WEBP, "image/webp", ".webp", True),
    ],
)
def test_a_pdf_and_the_common_image_types_are_recognised_by_their_leading_bytes(
    head: bytes, content_type: str, extension: str, is_image: bool
) -> None:
    file_type = sniff(head)

    assert file_type is not None
    assert (file_type.content_type, file_type.extension, file_type.is_image) == (
        content_type,
        extension,
        is_image,
    )
    assert sniff(head[:SNIFF_BYTES]) == file_type


@pytest.mark.parametrize(
    "head",
    [
        b"",
        b"%PDF",
        b" %PDF-1.7",
        b"\n%PDF-1.7",
        b"<html><script>alert(1)</script>",
        b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'>",
        b"<svg onload=alert(1)>",
        b"MZ\x90\x00\x03\x00\x00\x00",
        b"\x7fELF\x02\x01\x01\x00",
        b"PK\x03\x04\x14\x00\x00\x00",
        b"#!/bin/sh\nrm -rf /",
        b"GIF88a\x01\x00",
        b"RIFF\x24\x00\x00\x00WAVEfmt ",
        b"RIFF\x24\x00",
        b"\x89PNG\r\n",
        b"\xff\xd8",
        b"BM\x36\x00\x0c\x00",
        b"plain text",
    ],
)
def test_anything_else_is_not_recognised(head: bytes) -> None:
    assert sniff(head) is None


def test_every_type_names_itself_once_and_jpeg_answers_to_both_extensions() -> None:
    content_types = [file_type.content_type for file_type in FILE_TYPES]

    assert sorted(content_types) == sorted(set(content_types))
    assert "image/svg+xml" not in content_types
    jpeg = sniff(JPEG)
    assert jpeg is not None
    assert jpeg.extensions == (".jpg", ".jpeg")
