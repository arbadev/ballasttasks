"""Maps application and domain errors to HTTP, in one place.

Error bodies keep FastAPI's two shapes: ``{"detail": "<message>"}`` (``ErrorResponse``)
and, for ``422``, ``{"detail": [{"type", "loc", "msg"}, ...]}`` (``HTTPValidationError``),
whether the request was rejected by a Pydantic model or by a domain rule.
"""

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.application.errors import TaskNotFound
from app.domain.task import InvalidTaskError


async def _task_not_found(_: Request, error: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})


async def _invalid_task(_: Request, error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": [{"type": "invalid_task", "loc": ["body"], "msg": str(error)}]},
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


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_error_without_input)
    app.add_exception_handler(TaskNotFound, _task_not_found)
    app.add_exception_handler(InvalidTaskError, _invalid_task)
