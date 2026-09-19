"""Maps application and domain errors to HTTP, in one place.

Error bodies keep FastAPI's two shapes: ``{"detail": "<message>"}`` (``ErrorResponse``)
and, for ``422``, ``{"detail": [{"type", "loc", "msg"}, ...]}`` (``HTTPValidationError``),
whether the request was rejected by a Pydantic model or by a domain rule.
"""

from fastapi import FastAPI, Request, status
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


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(TaskNotFound, _task_not_found)
    app.add_exception_handler(InvalidTaskError, _invalid_task)
