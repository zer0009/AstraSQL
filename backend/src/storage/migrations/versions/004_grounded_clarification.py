"""Add connections.grounded_clarification_enabled

Revision ID: 004_grounded_clarification
Revises: 003_auth
Create Date: 2026-10-01

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_grounded_clarification"
down_revision: str | None = "003_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column("grounded_clarification_enabled", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("connections", "grounded_clarification_enabled")
