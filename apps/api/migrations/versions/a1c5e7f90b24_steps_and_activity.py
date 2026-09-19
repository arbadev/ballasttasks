"""steps and activity

The steps (subtasks) of a task and its append-only activity: log lines and comments.

Revision ID: a1c5e7f90b24
Revises: 8b2f4c6d1a3e
Create Date: 2026-09-18 23:19:29.127513

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c5e7f90b24"
down_revision: str | Sequence[str] | None = "8b2f4c6d1a3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ``app.domain.activity_log.CREATED``, spelled out: a revision must keep meaning what it meant
# on the day it was written, whatever the application code says later.
CREATED = "Created the task"


def upgrade() -> None:
    """Two tables that hang off ``tasks``. It must work on a database that already holds tasks.

    What happens to existing rows, decided here and proven in
    ``tests/integration/test_steps_activity_migration.py``:

    - no task is touched, not even its ``updated_at``;
    - every existing task gets the entry the design gives every task, "Created the task",
      by its creator (``tasks.created_by``, a user the foreign key guarantees, active or
      not) and at its ``created_at``. Without it the oldest tasks would be the only ones
      whose timeline does not start with their creation. What else happened to them before
      today was never recorded and is not invented;
    - existing tasks get no steps: they had none.

    Both tables go when their task goes (``ON DELETE CASCADE``). Step positions are unique
    per task with a DEFERRABLE constraint, checked when the transaction ends, so a reorder
    may pass through a state where two steps share a position. ``task_activity.seq`` is the
    order of writing; it orders entries of one instant. Reasons: ADR 0007.
    """
    op.create_table(
        "task_activity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('log', 'comment')", name=op.f("ck_task_activity_kind")),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_task_activity_actor_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_task_activity_task_id_tasks", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_activity")),
    )
    op.create_index(op.f("ix_task_activity_actor_id"), "task_activity", ["actor_id"], unique=False)
    op.create_index(
        "ix_task_activity_comments_task_id",
        "task_activity",
        ["task_id"],
        unique=False,
        postgresql_where=sa.text("kind = 'comment'"),
    )
    op.create_index(
        "ix_task_activity_task_id_created_at_seq",
        "task_activity",
        ["task_id", "created_at", "seq"],
        unique=False,
    )
    op.create_table(
        "task_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("position >= 0", name=op.f("ck_task_steps_position")),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_task_steps_task_id_tasks", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_steps")),
        sa.UniqueConstraint(
            "task_id",
            "position",
            deferrable=True,
            initially="DEFERRED",
            name="uq_task_steps_task_id_position",
        ),
    )
    # Oldest first, so ``seq`` runs the way time did. ``gen_random_uuid`` is built in since
    # PostgreSQL 13.
    op.execute(
        sa.text(
            "INSERT INTO task_activity (id, task_id, kind, text, actor_id, created_at) "
            "SELECT gen_random_uuid(), id, 'log', :created, created_by, created_at "
            "FROM tasks ORDER BY created_at, id"
        ).bindparams(created=CREATED)
    )


def downgrade() -> None:
    """Drop both tables, and with them every step, comment and log line: the schema before
    this revision has nowhere to keep them. Tasks are left exactly as they are."""
    op.drop_table("task_steps")
    op.drop_index("ix_task_activity_task_id_created_at_seq", table_name="task_activity")
    op.drop_index(
        "ix_task_activity_comments_task_id",
        table_name="task_activity",
        postgresql_where=sa.text("kind = 'comment'"),
    )
    op.drop_index(op.f("ix_task_activity_actor_id"), table_name="task_activity")
    op.drop_table("task_activity")
