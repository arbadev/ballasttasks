"""Errors the application layer raises; the presentation layer maps them to HTTP."""

import uuid


class TaskNotFound(LookupError):  # noqa: N818 - named for what happened, as the API reports it
    def __init__(self, task_id: uuid.UUID) -> None:
        super().__init__(f"Task {task_id} not found")
        self.task_id = task_id


class StoredTaskInvalid(RuntimeError):  # noqa: N818 - named for what happened
    """A stored task breaks a domain rule: a server fault, never the caller's request."""

    def __init__(self, task_id: uuid.UUID) -> None:
        super().__init__(f"Stored task {task_id} is invalid")
        self.task_id = task_id
