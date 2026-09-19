"""ORM models. Importing this package registers every table on ``Base.metadata``.

New model = new module here plus one import line below (Alembic's env.py imports the package).
"""

from app.infrastructure.db.models.activity import ActivityModel
from app.infrastructure.db.models.attachment import AttachmentModel
from app.infrastructure.db.models.project import ProjectModel
from app.infrastructure.db.models.step import StepModel
from app.infrastructure.db.models.task import TaskModel
from app.infrastructure.db.models.user import UserModel
from app.infrastructure.db.models.user_identity import UserIdentityModel

__all__ = [
    "ActivityModel",
    "AttachmentModel",
    "ProjectModel",
    "StepModel",
    "TaskModel",
    "UserIdentityModel",
    "UserModel",
]
