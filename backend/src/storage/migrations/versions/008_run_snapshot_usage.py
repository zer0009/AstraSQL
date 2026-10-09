"""Add run_snapshots table and query_history.usage_json

Revision ID: 008_run_snapshot_usage
Revises: 007_trust_level
Create Date: 2026-10-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "008_run_snapshot_usage"
down_revision: str | None = "007_trust_level"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "run_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(length=36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "session_id",
            sa.String(length=36),
            sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "history_id",
            sa.String(length=36),
            sa.ForeignKey("query_history.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=True),
        sa.Column("assumption", sa.Text(), nullable=True),
        sa.Column("alternatives_json", sa.Text(), nullable=True),
        sa.Column("ambiguity_json", sa.Text(), nullable=True),
        sa.Column("sql", sa.Text(), nullable=True),
        sa.Column("context_version", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.add_column(
        "query_history",
        sa.Column("usage_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "query_history",
        sa.Column("run_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("query_history", "run_id")
    op.drop_column("query_history", "usage_json")
    op.drop_table("run_snapshots")
