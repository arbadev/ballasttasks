"""Who is calling: the seam between the task routes and authentication.

Routes depend on ``CurrentUserId`` and nothing else: they never see a token, a User or
the users table. INTERIM BODY: authentication is built separately; until its
implementation replaces this function, every request is rejected as unauthenticated.
Tests provide a user through ``app.dependency_overrides[get_current_user_id]``.
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status


async def get_current_user_id() -> uuid.UUID:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
