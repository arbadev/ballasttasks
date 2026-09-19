"""create tasks

Revision ID: 538d7dc736b3
Revises: 23cd5b1da963
Create Date: 2026-09-18 19:26:43.707078

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "538d7dc736b3"
down_revision: str | Sequence[str] | None = "23cd5b1da963"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Tasks. ``created_by`` and ``assignee_id`` get their foreign keys in ``fa7b13ec7508``."""
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'done')", name=op.f("ck_tasks_status")
        ),
        sa.CheckConstraint(
            "(status = 'done') = (completed_at IS NOT NULL)",
            name=op.f("ck_tasks_completed_at_follows_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(op.f("ix_tasks_due_date"), "tasks", ["due_date"], unique=False)
    op.create_index(op.f("ix_tasks_status"), "tasks", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tasks_status"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_due_date"), table_name="tasks")
    op.drop_table("tasks")
