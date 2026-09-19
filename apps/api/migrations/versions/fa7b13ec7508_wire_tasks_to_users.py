"""wire tasks to users

Revision ID: fa7b13ec7508
Revises: 2dcaf48d517c
Create Date: 2026-09-18 20:55:00.344963

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa7b13ec7508"
down_revision: str | Sequence[str] | None = "2dcaf48d517c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# What makes a placeholder recognisable: a reserved domain nobody can receive mail at
# (RFC 2606), an account that is not active, and a "hash" no password can ever match.
INSERT_PLACEHOLDER_CREATORS = (
    "INSERT INTO users (id, email, full_name, hashed_password, is_active, created_at) "
    "SELECT orphans.created_by, 'unknown-' || orphans.created_by::text || '@placeholder.invalid', "
    "'Unknown user', '!', false, now() "
    "FROM (SELECT DISTINCT created_by FROM tasks) AS orphans "
    "WHERE NOT EXISTS (SELECT 1 FROM users WHERE users.id = orphans.created_by)"
)
DELETE_PLACEHOLDER_CREATORS = (
    "DELETE FROM users "
    "WHERE email = 'unknown-' || users.id::text || '@placeholder.invalid' "
    "AND hashed_password = '!' AND NOT is_active"
)


def upgrade() -> None:
    """Foreign keys from ``tasks.created_by`` and ``tasks.assignee_id`` to ``users.id``.

    ON DELETE, one deliberate choice per column:

    - ``created_by`` RESTRICT: a task must not silently lose its creator, so a user who
      created tasks cannot be deleted; deactivate them instead.
    - ``assignee_id`` SET NULL: when an assignee goes away, the task stays and is unassigned.

    Until now both columns were plain UUIDs that nothing checked, so an existing database
    can hold ids that match no user. No task is deleted and the upgrade does not fail:

    - an ``assignee_id`` that matches no user is set to NULL, exactly what SET NULL would
      have done had the key existed when that user went away. ``updated_at`` is left alone:
      nobody edited the task.
    - a ``created_by`` that matches no user cannot become NULL (the column is NOT NULL, a
      task always has a creator). The id is kept, and an INACTIVE placeholder user is
      inserted under that same id, one per distinct id. It cannot log in (inactive, and its
      hash matches no password), and ``GET /tasks`` answers exactly what it did before.

    Both columns get an index: RESTRICT and SET NULL make every user delete look tasks up by
    them, and they are the columns the task list will be filtered by.
    """
    op.execute(
        "UPDATE tasks SET assignee_id = NULL "
        "WHERE assignee_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM users WHERE users.id = tasks.assignee_id)"
    )
    op.execute(INSERT_PLACEHOLDER_CREATORS)
    op.create_index(op.f("ix_tasks_assignee_id"), "tasks", ["assignee_id"], unique=False)
    op.create_index(op.f("ix_tasks_created_by"), "tasks", ["created_by"], unique=False)
    op.create_foreign_key(
        op.f("fk_tasks_created_by_users"),
        "tasks",
        "users",
        ["created_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_tasks_assignee_id_users"),
        "tasks",
        "users",
        ["assignee_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Drop the keys and indexes, then the placeholder users ``upgrade`` invented.

    Tasks keep their ``created_by``, so they are back to what they were. An assignee that
    ``upgrade`` cleared stays cleared: that id pointed at nobody and was not kept anywhere.
    """
    op.drop_constraint(op.f("fk_tasks_assignee_id_users"), "tasks", type_="foreignkey")
    op.drop_constraint(op.f("fk_tasks_created_by_users"), "tasks", type_="foreignkey")
    op.drop_index(op.f("ix_tasks_created_by"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_assignee_id"), table_name="tasks")
    op.execute(DELETE_PLACEHOLDER_CREATORS)
