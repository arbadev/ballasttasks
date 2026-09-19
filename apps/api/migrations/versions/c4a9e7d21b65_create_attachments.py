"""create attachments

The ``attachments`` table: the links and stored files of a task.

Revision ID: c4a9e7d21b65
Revises: 0ecd0978f6fd
Create Date: 2026-09-18 23:11:17.034705

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4a9e7d21b65"
down_revision: str | Sequence[str] | None = "0ecd0978f6fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """One new table; nothing existing is altered. It must work on a database that already
    holds tasks.

    What happens to existing rows, decided here and proven in
    ``tests/integration/test_attachments_migration.py``:

    - no task, user or project is edited: ``attachments_count`` is computed from this table
      and never stored on the task, so every existing task simply starts with no attachments
      and needs no backfill;
    - ``task_id`` is ``ON DELETE CASCADE`` (an attachment is part of its task) and
      ``created_by`` is ``ON DELETE RESTRICT``, like ``tasks.created_by``;
    - the CHECK constraints only stop a row no attachment could be rebuilt from: a link has a
      URL and no file fields, a ``pdf`` or ``image`` has all three file fields and no URL;
    - ``storage_key`` is unique, so two rows never share a stored file.
    """
    op.create_table(
        "attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("storage_key", sa.String(length=200), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "(kind = 'link' AND url IS NOT NULL AND storage_key IS NULL "
            "AND content_type IS NULL AND size_bytes IS NULL) "
            "OR (NOT kind = 'link' AND url IS NULL AND storage_key IS NOT NULL "
            "AND content_type IS NOT NULL AND size_bytes IS NOT NULL)",
            name=op.f("ck_attachments_fields_follow_kind"),
        ),
        sa.CheckConstraint("kind IN ('link', 'pdf', 'image')", name=op.f("ck_attachments_kind")),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_attachments_size_bytes_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_attachments_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_attachments_task_id_tasks", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
        sa.UniqueConstraint("storage_key", name="uq_attachments_storage_key"),
    )
    op.create_index(op.f("ix_attachments_created_by"), "attachments", ["created_by"], unique=False)
    op.create_index(op.f("ix_attachments_task_id"), "attachments", ["task_id"], unique=False)


def downgrade() -> None:
    """Drops the table, and with it every attachment row: the older schema has nowhere to
    keep them. Tasks are left exactly as they are.

    Files already written by a ``FileStorage`` adapter are NOT removed (a revision cannot
    reach the storage); after a downgrade they are orphans to be cleared by hand.
    """
    op.drop_index(op.f("ix_attachments_task_id"), table_name="attachments")
    op.drop_index(op.f("ix_attachments_created_by"), table_name="attachments")
    op.drop_table("attachments")
