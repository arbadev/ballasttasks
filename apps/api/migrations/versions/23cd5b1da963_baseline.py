"""baseline

Revision ID: 23cd5b1da963
Revises:
Create Date: 2026-09-18 18:16:16.108090

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "23cd5b1da963"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
