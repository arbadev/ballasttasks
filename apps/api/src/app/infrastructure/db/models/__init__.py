"""Importing this package registers every ORM model on ``Base.metadata`` (Alembic needs that).

New model = new module here + one import line below.
"""

from app.infrastructure.db.models.user import UserModel

__all__ = ["UserModel"]
