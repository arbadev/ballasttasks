from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Body of every error except request validation (``422`` uses ``HTTPValidationError``)."""

    detail: str
