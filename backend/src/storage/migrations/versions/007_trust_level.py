"""Add query_history.trust_level

Revision ID: 007_trust_level
Revises: 006_ambiguity_json
Create Date: 2026-10-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "007_trust_level"
down_revision: str | None = "006_ambiguity_json"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "query_history",
        sa.Column("trust_level", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("query_history", "trust_level")
