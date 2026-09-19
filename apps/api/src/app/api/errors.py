"""Maps application and domain errors to HTTP, in one place.

Error bodies keep FastAPI's two shapes: ``{"detail": "<message>"}`` (``ErrorResponse``)
and, for ``422``, ``{"detail": [{"type", "loc", "msg"}, ...]}`` (``HTTPValidationError``),
whether the request was rejected by a Pydantic model or by a domain rule.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.application.errors import (
    AttachmentHasNoContent,
    AttachmentNotFound,
    EmptyFileError,
    FileTooLargeError,
    InvalidAssigneeError,
    InvalidTaskReferenceError,
    ProjectKeyTakenError,
    ProjectNotFound,
    StepNotFound,
    TaskNotFound,
    UnknownProjectError,
    UnsupportedFileTypeError,
)
from app.application.ports.step_generation_jobs import GenerationJobsUnavailable
from app.application.step_generation import GenerationNotFound
from app.domain.activity import InvalidActivityError
from app.domain.attachment import InvalidAttachmentError
from app.domain.project import InvalidProjectError
from app.domain.step import InvalidStepError, InvalidStepOrderError
from app.domain.task import InvalidTaskError
from app.domain.user import InvalidProfileError

ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]


async def _not_found(_: Request, error: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})


async def _conflict(_: Request, error: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error)})


def _unprocessable(kind: str, loc: list[str]) -> ExceptionHandler:
    """A rule the request broke, in the shape of FastAPI's own ``422``."""

    async def handler(_: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": [{"type": kind, "loc": loc, "msg": str(error)}]},
        )

    return handler


async def _invalid_task(_: Request, error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": [{"type": "invalid_task", "loc": ["body"], "msg": str(error)}]},
    )


async def _invalid_assignee(_: Request, error: Exception) -> JSONResponse:
    """The same body whether the use case's check or the foreign key refused the assignee,
    and whether the id is unknown or belongs to a deactivated user."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": [
                {"type": "invalid_assignee", "loc": ["body", "assignee_id"], "msg": str(error)}
            ]
        },
    )


async def _validation_error_without_input(_: Request, error: Exception) -> JSONResponse:
    """FastAPI's 422 body, minus ``input``.

    Pydantic reports the offending value, and for a missing field that value is the whole
    request body: a rejected registration would send the password straight back (and into
    any client-side log). ``loc``, ``msg`` and ``type`` say everything a client needs.
    """
    assert isinstance(error, RequestValidationError)  # noqa: S101  (registered for this type)
    details = [{k: v for k, v in item.items() if k != "input"} for item in error.errors()]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(details)},
    )


async def _generation_unavailable(_: Request, error: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(error)})


def _file_error(code: int) -> ExceptionHandler:
    async def handler(_: Request, error: Exception) -> JSONResponse:
        return JSONResponse(status_code=code, content={"detail": str(error)})

    return handler


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(GenerationNotFound, _not_found)
    app.add_exception_handler(GenerationJobsUnavailable, _generation_unavailable)
    app.add_exception_handler(AttachmentHasNoContent, _not_found)
    app.add_exception_handler(EmptyFileError, _unprocessable("empty_file", ["body", "file"]))
    app.add_exception_handler(FileTooLargeError, _file_error(413))
    app.add_exception_handler(UnsupportedFileTypeError, _file_error(415))
    app.add_exception_handler(RequestValidationError, _validation_error_without_input)
    app.add_exception_handler(TaskNotFound, _not_found)
    app.add_exception_handler(ProjectNotFound, _not_found)
    app.add_exception_handler(AttachmentNotFound, _not_found)
    app.add_exception_handler(StepNotFound, _not_found)
    app.add_exception_handler(ProjectKeyTakenError, _conflict)
    app.add_exception_handler(
        InvalidTaskReferenceError, _unprocessable("invalid_task_reference", ["path", "id_or_key"])
    )
    app.add_exception_handler(
        UnknownProjectError, _unprocessable("unknown_project", ["body", "project_id"])
    )
    app.add_exception_handler(InvalidProjectError, _unprocessable("invalid_project", ["body"]))
    app.add_exception_handler(InvalidProfileError, _unprocessable("invalid_profile", ["body"]))
    app.add_exception_handler(
        InvalidAttachmentError, _unprocessable("invalid_attachment", ["body"])
    )
    app.add_exception_handler(InvalidStepError, _unprocessable("invalid_step", ["body"]))
    app.add_exception_handler(
        InvalidStepOrderError, _unprocessable("invalid_step_order", ["body", "step_ids"])
    )
    app.add_exception_handler(InvalidActivityError, _unprocessable("invalid_comment", ["body"]))
    app.add_exception_handler(InvalidTaskError, _invalid_task)
    app.add_exception_handler(InvalidAssigneeError, _invalid_assignee)
