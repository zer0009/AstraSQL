from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import connections, context, export, history, query
from src.api.routers import settings as settings_router
from src.config.settings import get_settings
from src.storage.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title=cfg.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok", "app": cfg.app_name}

    app.include_router(connections.router, prefix="/api/connections")
    app.include_router(context.router, prefix="/api/context")
    app.include_router(query.router, prefix="/api/query")
    app.include_router(history.router, prefix="/api/history")
    app.include_router(export.router, prefix="/api/export")
    app.include_router(settings_router.router, prefix="/api/settings")

    return app


app = create_app()
