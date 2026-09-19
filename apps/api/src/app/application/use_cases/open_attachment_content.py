import uuid
from collections.abc import AsyncIterator

from app.application.errors import (
    AttachmentContentMissing,
    AttachmentHasNoContent,
    AttachmentNotFound,
)
from app.application.ports.attachment_repository import AttachmentRepository
from app.application.ports.file_storage import FileStorage, StoredFileNotFound
from app.domain.attachment import Attachment


class OpenAttachmentContent:
    def __init__(self, attachments: AttachmentRepository, storage: FileStorage) -> None:
        self._attachments = attachments
        self._storage = storage

    async def execute(
        self, task_id: uuid.UUID, attachment_id: uuid.UUID
    ) -> tuple[Attachment, AsyncIterator[bytes]]:
        attachment = await self._attachments.get(attachment_id)
        if attachment is None or attachment.task_id != task_id:
            raise AttachmentNotFound(attachment_id)
        if attachment.storage_key is None:
            raise AttachmentHasNoContent
        try:
            chunks = await self._storage.open(attachment.storage_key)
        except StoredFileNotFound:
            raise AttachmentContentMissing(attachment_id) from None
        return attachment, chunks
