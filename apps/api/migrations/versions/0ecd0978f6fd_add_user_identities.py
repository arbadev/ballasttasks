"""add user identities

Revision ID: 0ecd0978f6fd
Revises: fa7b13ec7508
Create Date: 2026-09-18 22:12:53.096804

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0ecd0978f6fd"
down_revision: str | Sequence[str] | None = "fa7b13ec7508"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The hash no password matches: no Argon2 hash looks like this, so verification fails.
# The same marker the placeholder users of revision fa7b13ec7508 carry.
UNMATCHABLE_HASH = "!"


def upgrade() -> None:
    """Identities at external providers, and users who have no password.

    - ``user_identities``: ``(provider, subject)`` is unique (an identity is one user) and so
      is ``(user_id, provider)`` (a user has one identity per provider). ON DELETE CASCADE:
      an identity means nothing without its user. The second unique index starts with
      ``user_id``, so it also serves the cascade's lookup and no extra index is needed.
    - ``users.hashed_password`` becomes nullable: NULL is "no password", the state of a user
      created by single sign-on. Password login refuses such a user.

    Existing rows: nothing is rewritten. Every user keeps their hash and stays a password
    user; nobody has an identity yet, and one is linked the first time they sign in through
    a provider that reports their email as verified. Dropping NOT NULL is a catalogue change,
    so the upgrade does not scan or lock out a populated table for long.
    """
    op.create_table(
        "user_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_identities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_identities")),
        sa.UniqueConstraint("provider", "subject", name="uq_user_identities_provider_subject"),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_identities_user_id_provider"),
    )
    op.alter_column("users", "hashed_password", existing_type=sa.VARCHAR(length=255), nullable=True)


def downgrade() -> None:
    """Back to "every user has a hash", without losing a user or a task.

    A user with no password cannot simply be deleted: ``tasks.created_by`` is ON DELETE
    RESTRICT, and their tasks must survive. They get the hash no password matches instead,
    so they stay, their tasks stay, and they cannot log in with a password (they never
    could). The identities are dropped with the table: after a later upgrade such a user is
    linked again at their next sign-in, by their verified email.
    """
    op.execute(
        sa.text(
            "UPDATE users SET hashed_password = :hash WHERE hashed_password IS NULL"
        ).bindparams(hash=UNMATCHABLE_HASH)
    )
    op.alter_column(
        "users", "hashed_password", existing_type=sa.VARCHAR(length=255), nullable=False
    )
    op.drop_table("user_identities")
