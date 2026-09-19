import uuid
from collections.abc import Callable

from app.application.clock import Clock, utc_now
from app.application.errors import TaskNotFound
from app.application.ports.activity_recorder import ActivityRecorder
from app.application.ports.attachment_repository import AttachmentRepository
from app.application.ports.task_repository import TaskRepository
from app.domain import activity_log
from app.domain.activity import ActivityEntry
from app.domain.attachment import Attachment


class AttachLink:
    def __init__(
        self,
        tasks: TaskRepository,
        attachments: AttachmentRepository,
        activity: ActivityRecorder,
        *,
        clock: Clock = utc_now,
        new_id: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._tasks = tasks
        self._attachments = attachments
        self._activity = activity
        self._clock = clock
        self._new_id = new_id

    async def execute(
        self, task_id: uuid.UUID, *, url: str, name: str | None, created_by: uuid.UUID
    ) -> Attachment:
        """Attach a link, named after its host unless ``name`` says otherwise.

        Raises ``TaskNotFound``, and ``InvalidAttachmentError`` when the URL or the name
        breaks a domain rule. Attaching counts as work on the task: it touches ``updated_at``,
        as the design's ``addAttachment`` does.
        """
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        now = self._clock()
        link = Attachment.link(
            attachment_id=self._new_id(),
            task_id=task_id,
            url=url,
            name=name,
            created_by=created_by,
            now=now,
        )
        await self._attachments.add(link)
        task.touch(now=now)
        await self._tasks.update(task)
        await self._activity.record(
            ActivityEntry.log(
                entry_id=self._new_id(),
                task_id=task_id,
                actor_id=created_by,
                text=activity_log.attachment_added(link.name),
                now=now,
            )
        )
        return link
