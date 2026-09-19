"""Incremental multipart parsing: no UploadFile spooling before the size check.

Exactly one ``file`` part. At most 64 KiB is handed to the parser at a time;
headers are bounded separately. Validation continues through the closing boundary
so malformed/truncated requests roll back any file already written.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header


def invalid_upload() -> RequestValidationError:
    return RequestValidationError(
        [
            {
                "type": "invalid_upload",
                "loc": ["body", "file"],
                "msg": "Expected one complete multipart file part named file",
            }
        ]
    )


class StreamingUpload:
    def __init__(self, request: Request) -> None:
        media_type, options = parse_options_header(request.headers.get("content-type", ""))
        boundary = options.get(b"boundary", b"")
        if media_type != b"multipart/form-data" or not boundary or len(boundary) > 200:
            raise invalid_upload()
        self.name: str | None = None
        self._headers_ready = False
        self._ended = False
        self._parts = 0
        self._header_bytes = 0
        self._body_bytes = 0
        self._data_bytes = 0
        self._field = bytearray()
        self._value = bytearray()
        self._headers: dict[bytes, bytes] = {}
        self._pending: list[bytes] = []
        self._request = request
        self._parser = MultipartParser(
            boundary,
            {
                "on_part_begin": self._part_begin,
                "on_header_field": self._header_field,
                "on_header_value": self._header_value,
                "on_header_end": self._header_end,
                "on_headers_finished": self._headers_finished,
                "on_part_data": self._data,
                "on_end": self._end,
            },
        )
        self._chunks = self._parse()
        self._first: bytes | None = None

    def _part_begin(self) -> None:
        self._parts += 1
        if self._parts > 1:
            raise invalid_upload()

    def _header(self, target: bytearray, data: bytes, start: int, end: int) -> None:
        self._header_bytes += end - start
        if self._header_bytes > 16 * 1024:
            raise invalid_upload()
        target.extend(data[start:end])

    def _header_field(self, data: bytes, start: int, end: int) -> None:
        self._header(self._field, data, start, end)

    def _header_value(self, data: bytes, start: int, end: int) -> None:
        self._header(self._value, data, start, end)

    def _header_end(self) -> None:
        field = bytes(self._field).lower()
        if field in self._headers:
            raise invalid_upload()
        self._headers[field] = bytes(self._value)
        self._field.clear()
        self._value.clear()

    def _headers_finished(self) -> None:
        disposition, options = parse_options_header(self._headers.get(b"content-disposition", b""))
        if (
            disposition != b"form-data"
            or options.get(b"name") != b"file"
            or b"filename" not in options
        ):
            raise invalid_upload()
        self.name = options[b"filename"].decode("utf-8", errors="replace")
        self._headers_ready = True

    def _data(self, data: bytes, start: int, end: int) -> None:
        self._data_bytes += end - start
        self._pending.append(data[start:end])

    def _end(self) -> None:
        self._ended = True

    async def _parse(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._request.stream():
                for offset in range(0, len(chunk), 64 * 1024):
                    piece = chunk[offset : offset + 64 * 1024]
                    self._body_bytes += len(piece)
                    self._parser.write(piece)
                    if self._body_bytes - self._data_bytes > 32 * 1024:
                        raise invalid_upload()
                    if self._headers_ready:
                        # Even an empty file announces its name before the use case reads it.
                        yield b"".join(self._pending)
                        self._pending.clear()
            self._parser.finalize()
        except MultipartParseError:
            raise invalid_upload() from None
        if not self._headers_ready or not self._ended:
            raise invalid_upload()

    async def prepare(self) -> None:
        try:
            self._first = await anext(self._chunks)
        except StopAsyncIteration:
            raise invalid_upload() from None

    async def chunks(self) -> AsyncIterator[bytes]:
        if self._first is not None:
            yield self._first
            self._first = None
        async for chunk in self._chunks:
            yield chunk
