from __future__ import annotations

from fastapi import APIRouter

from src.api.schemas import PublicSettingsOut
from src.config.settings import get_settings
from src.providers.database import list_database_types

router = APIRouter(tags=["settings"])


@router.get("/public", response_model=PublicSettingsOut)
async def public_settings() -> PublicSettingsOut:
    settings = get_settings()
    return PublicSettingsOut(
        app_name=settings.app_name,
        llm_provider=settings.llm_provider,
        model=settings.openai_model,
        max_rows=settings.max_result_rows,
        database_types=list_database_types(),
    )
