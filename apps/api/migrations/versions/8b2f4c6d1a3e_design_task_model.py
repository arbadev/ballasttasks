"""design task model

Projects, task keys, the testing status, priority, importance, and the users' role label.

Revision ID: 8b2f4c6d1a3e
Revises: fa7b13ec7508
Create Date: 2026-09-19 09:30:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b2f4c6d1a3e"
down_revision: str | Sequence[str] | None = "fa7b13ec7508"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ``app.domain.project.DEFAULT_PROJECT_ID``, spelled out: a revision must keep meaning what
# it meant on the day it was written, whatever the application code says later.
INBOX_ID = "00000000-0000-4000-8000-000000000001"

OLD_STATUSES = "status IN ('todo', 'in_progress', 'done')"
NEW_STATUSES = "status IN ('todo', 'in_progress', 'testing', 'done')"


def upgrade() -> None:
    """The model the design shows. It must work on a database that already holds tasks.

    What happens to existing rows, decided here and proven in
    ``tests/integration/test_design_model_migration.py``:

    - no task is deleted or edited: title, status, dates, people and ``updated_at`` stay as
      they are (nobody touched the task), and the three old statuses are still valid;
    - every existing task moves into the "Inbox" project (key ``IN``), which this revision
      creates in every database, empty ones included: it is where a task without a project
      lands. Existing tasks get the keys ``IN-01``, ``IN-02``, ... in the order they were
      created (``created_at``, then ``id``), and the Inbox counter continues after them;
    - existing tasks get the design's defaults for a new task: priority ``P2`` (stored as
      its rank, 2) and importance 50;
    - existing users get no role label.
    """
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key", sa.String(length=5), nullable=False),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("next_task_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("key ~ '^[A-Z]{2,5}$'", name=op.f("ck_projects_key_shape")),
        sa.CheckConstraint(
            "next_task_number >= 1", name=op.f("ck_projects_next_task_number_positive")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("key", name="uq_projects_key"),
    )
    inbox = sa.bindparam("inbox", uuid.UUID(INBOX_ID), type_=sa.Uuid())
    op.execute(
        sa.text(
            "INSERT INTO projects "
            "(id, name, key, color, next_task_number, created_at, updated_at) "
            "SELECT :inbox, 'Inbox', 'IN', NULL, count(*) + 1, now(), now() FROM tasks"
        ).bindparams(inbox)
    )

    op.add_column("users", sa.Column("role_label", sa.String(length=60), nullable=True))

    # Nullable (or defaulted) while the existing rows are filled in, strict afterwards.
    op.add_column("tasks", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.add_column("tasks", sa.Column("key", sa.String(length=16), nullable=True))
    op.add_column(
        "tasks", sa.Column("priority", sa.SmallInteger(), server_default="2", nullable=False)
    )
    op.add_column(
        "tasks", sa.Column("importance", sa.SmallInteger(), server_default="50", nullable=False)
    )
    op.execute(
        sa.text(
            "UPDATE tasks SET project_id = :inbox, "
            "key = 'IN-' || CASE WHEN numbered.n < 10 THEN '0' ELSE '' END || numbered.n::text "
            "FROM (SELECT id, row_number() OVER (ORDER BY created_at, id) AS n FROM tasks) "
            "AS numbered WHERE tasks.id = numbered.id"
        ).bindparams(inbox)
    )
    op.alter_column("tasks", "project_id", nullable=False)
    op.alter_column("tasks", "key", nullable=False)
    op.alter_column("tasks", "priority", server_default=None)
    op.alter_column("tasks", "importance", server_default=None)

    op.create_foreign_key(
        op.f("fk_tasks_project_id_projects"),
        "tasks",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint("uq_tasks_key", "tasks", ["key"])
    op.create_check_constraint(op.f("ck_tasks_priority"), "tasks", "priority BETWEEN 0 AND 3")
    op.create_check_constraint(op.f("ck_tasks_importance"), "tasks", "importance BETWEEN 0 AND 100")
    op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"], unique=False)
    op.create_index(op.f("ix_tasks_updated_at"), "tasks", ["updated_at"], unique=False)
    # The default listing and the sidebar counts look only at open tasks.
    op.create_index(
        "ix_tasks_open_project_id_due_date",
        "tasks",
        ["project_id", "due_date"],
        unique=False,
        postgresql_where=sa.text("status <> 'done'"),
    )

    # Widening the vocabulary keeps every existing row valid. ``completed_at`` still follows
    # ``status = 'done'``, so "testing" is open work, as in the design.
    op.drop_constraint(op.f("ck_tasks_status"), "tasks", type_="check")
    op.create_check_constraint(op.f("ck_tasks_status"), "tasks", NEW_STATUSES)


def downgrade() -> None:
    """Back to tasks without projects.

    Tasks keep everything the previous schema can hold. What it cannot hold is dropped:
    project, key, priority, importance, every project, and the users' role labels. A task in
    ``testing`` becomes ``in_progress``, the closest status the old vocabulary has: it is
    open work either way, so ``completed_at`` stays empty and the completion rule still
    holds. ``updated_at`` is left alone.
    """
    op.execute("UPDATE tasks SET status = 'in_progress' WHERE status = 'testing'")
    op.drop_constraint(op.f("ck_tasks_status"), "tasks", type_="check")
    op.create_check_constraint(op.f("ck_tasks_status"), "tasks", OLD_STATUSES)

    op.drop_index("ix_tasks_open_project_id_due_date", table_name="tasks")
    op.drop_index(op.f("ix_tasks_updated_at"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_project_id"), table_name="tasks")
    op.drop_constraint(op.f("ck_tasks_importance"), "tasks", type_="check")
    op.drop_constraint(op.f("ck_tasks_priority"), "tasks", type_="check")
    op.drop_constraint("uq_tasks_key", "tasks", type_="unique")
    op.drop_constraint(op.f("fk_tasks_project_id_projects"), "tasks", type_="foreignkey")
    op.drop_column("tasks", "importance")
    op.drop_column("tasks", "priority")
    op.drop_column("tasks", "key")
    op.drop_column("tasks", "project_id")

    op.drop_column("users", "role_label")
    op.drop_table("projects")
