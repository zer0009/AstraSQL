from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    db_type: Mapped[str] = mapped_column(String(64), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    database: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False)
    ssl_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    schema_enrichments: Mapped[list[SchemaEnrichment]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )
    golden_records: Mapped[list[GoldenRecord]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )
    business_rules: Mapped[list[BusinessRule]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )
    query_history: Mapped[list[QueryHistory]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )
    chat_sessions: Mapped[list[ChatSession]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )
    schema_cache: Mapped[list[SchemaCache]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )


class SchemaEnrichment(Base):
    __tablename__ = "schema_enrichments"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "table_name", "column_name", name="uq_schema_enrichment"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    column_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    alias: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    example_values: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON text
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    connection: Mapped[Connection] = relationship(back_populates="schema_enrichments")


class GoldenRecord(Base):
    __tablename__ = "golden_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    connection: Mapped[Connection] = relationship(back_populates="golden_records")


class BusinessRule(Base):
    __tablename__ = "business_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    connection: Mapped[Connection] = relationship(back_populates="business_rules")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    connection: Mapped[Connection] = relationship(back_populates="chat_sessions")
    queries: Mapped[list[QueryHistory]] = relationship(
        back_populates="session",
        order_by="QueryHistory.turn_index",
    )


class QueryHistory(Base):
    __tablename__ = "query_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    turn_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    result_row_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    user_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    follow_ups: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON text
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    connection: Mapped[Connection] = relationship(back_populates="query_history")
    session: Mapped[Optional[ChatSession]] = relationship(back_populates="queries")


class SchemaCache(Base):
    __tablename__ = "schema_cache"
    __table_args__ = (
        UniqueConstraint("connection_id", "table_name", name="uq_schema_cache"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ddl_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    columns_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sample_rows_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    connection: Mapped[Connection] = relationship(back_populates="schema_cache")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="sessions")
