"""Add query_history.ambiguity_json

Revision ID: 006_ambiguity_json
Revises: 005_semantic_layer
Create Date: 2026-10-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_ambiguity_json"
down_revision: Union[str, None] = "005_semantic_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "query_history",
        sa.Column("ambiguity_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("query_history", "ambiguity_json")
