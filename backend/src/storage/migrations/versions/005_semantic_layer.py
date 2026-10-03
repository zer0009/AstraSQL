"""Add connections.semantic_layer_json

Revision ID: 005_semantic_layer
Revises: 004_grounded_clarification
Create Date: 2026-10-01

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_semantic_layer"
down_revision: str | None = "004_grounded_clarification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column("semantic_layer_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("connections", "semantic_layer_json")
