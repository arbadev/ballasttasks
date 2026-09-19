from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Body of every non-validation error: the same shape FastAPI's HTTPException emits."""

    detail: str
