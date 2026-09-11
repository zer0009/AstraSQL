"""Add chat_sessions and link query_history

Revision ID: 002_chat_sessions
Revises: 001_initial
Create Date: 2026-09-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_chat_sessions"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_sessions_connection_id"),
        "chat_sessions",
        ["connection_id"],
        unique=False,
    )

    with op.batch_alter_table("query_history") as batch_op:
        batch_op.add_column(sa.Column("session_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("turn_index", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_query_history_session_id",
            "chat_sessions",
            ["session_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_query_history_session_id"),
            ["session_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("query_history") as batch_op:
        batch_op.drop_index(op.f("ix_query_history_session_id"))
        batch_op.drop_constraint("fk_query_history_session_id", type_="foreignkey")
        batch_op.drop_column("turn_index")
        batch_op.drop_column("session_id")

    op.drop_index(op.f("ix_chat_sessions_connection_id"), table_name="chat_sessions")
    op.drop_table("chat_sessions")
