import uuid
from collections.abc import Collection, Mapping, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import AttachmentNotFound, StoredAttachmentInvalid, TaskNotFound
from app.domain.attachment import Attachment, AttachmentKind, InvalidAttachmentError
from app.infrastructure.db.constraints import violated_constraint
from app.infrastructure.db.models.attachment import TASK_FOREIGN_KEY, AttachmentModel

_FIELDS = (
    "id",
    "task_id",
    "name",
    "created_by",
    "created_at",
    "url",
    "storage_key",
    "content_type",
    "size_bytes",
)


class SqlAlchemyAttachmentRepository:
    """AttachmentRepository on PostgreSQL.

    Works inside the session it is given and never commits (see
    ``app.infrastructure.db.unit_of_work``). Every read is a SELECT, never the session's
    identity map: the rows of a deleted task go by ``ON DELETE CASCADE``, which the session
    does not hear about.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, attachment: Attachment) -> None:
        """The foreign key has the last word, inside a savepoint, so a task that vanishes
        between the use case's check and this write is still ``TaskNotFound`` and the rest
        of the unit of work stays usable."""
        row = AttachmentModel(
            kind=attachment.kind.value,
            **{field: getattr(attachment, field) for field in _FIELDS},
        )
        try:
            async with self._session.begin_nested():
                self._session.add(row)
        except IntegrityError as error:
            if violated_constraint(error) == TASK_FOREIGN_KEY:
                raise TaskNotFound(attachment.task_id) from error
            raise

    async def get(self, attachment_id: uuid.UUID) -> Attachment | None:
        row = await self._session.scalar(
            select(AttachmentModel).where(AttachmentModel.id == attachment_id)
        )
        return None if row is None else _to_attachment(row)

    async def list_for_task(self, task_id: uuid.UUID) -> Sequence[Attachment]:
        rows = await self._session.scalars(
            select(AttachmentModel)
            .where(AttachmentModel.task_id == task_id)
            .order_by(AttachmentModel.created_at, AttachmentModel.id)
        )
        return [_to_attachment(row) for row in rows]

    async def count_by_task(self, task_ids: Collection[uuid.UUID]) -> Mapping[uuid.UUID, int]:
        counts = dict.fromkeys(task_ids, 0)
        if not counts:
            return counts
        rows = await self._session.execute(
            select(AttachmentModel.task_id, func.count())
            .where(AttachmentModel.task_id.in_(counts))
            .group_by(AttachmentModel.task_id)
        )
        return counts | dict(rows.tuples().all())

    async def delete(self, attachment_id: uuid.UUID) -> None:
        deleted = await self._session.execute(
            delete(AttachmentModel)
            .where(AttachmentModel.id == attachment_id)
            .returning(AttachmentModel.id)
        )
        if deleted.first() is None:
            raise AttachmentNotFound(attachment_id)


def _to_attachment(row: AttachmentModel) -> Attachment:
    try:
        return Attachment(
            kind=AttachmentKind(row.kind), **{field: getattr(row, field) for field in _FIELDS}
        )
    except (InvalidAttachmentError, ValueError) as error:
        raise StoredAttachmentInvalid(row.id) from error
