from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import BusinessRule


class BusinessRulesStore:
    """Per-connection free-text business rules CRUD."""

    async def list(
        self, session: AsyncSession, connection_id: str
    ) -> list[BusinessRule]:
        result = await session.execute(
            select(BusinessRule)
            .where(BusinessRule.connection_id == connection_id)
            .order_by(BusinessRule.created_at)
        )
        return list(result.scalars().all())

    async def create(
        self, session: AsyncSession, connection_id: str, content: str
    ) -> BusinessRule:
        row = BusinessRule(connection_id=connection_id, content=content)
        session.add(row)
        await session.flush()
        return row

    async def update(
        self, session: AsyncSession, id: str, content: str
    ) -> BusinessRule | None:
        row = await session.get(BusinessRule, id)
        if row is None:
            return None
        row.content = content
        await session.flush()
        return row

    async def delete(self, session: AsyncSession, id: str) -> bool:
        row = await session.get(BusinessRule, id)
        if row is None:
            return False
        await session.delete(row)
        await session.flush()
        return True

    async def get_rules_text(self, session: AsyncSession, connection_id: str) -> str:
        rules = await self.list(session, connection_id)
        if not rules:
            return "(none)"
        return "\n".join(f"- {r.content.strip()}" for r in rules if r.content.strip())
