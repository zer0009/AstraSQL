from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.deps import require_ready_user
from src.api.routers import connections, context, export, history, query, sessions
from src.api.routers import auth as auth_router
from src.api.routers import settings as settings_router
from src.auth.exceptions import PasswordChangeRequiredError
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

    @app.exception_handler(PasswordChangeRequiredError)
    async def password_change_required_handler(request, exc: PasswordChangeRequiredError):
        return JSONResponse(
            status_code=403,
            content={"code": "PASSWORD_CHANGE_REQUIRED", "detail": str(exc)},
        )

    @app.get("/health")
    async def health():
        return {"status": "ok", "app": cfg.app_name}

    app.include_router(auth_router.router, prefix="/api/auth")

    protected = [Depends(require_ready_user)]
    app.include_router(connections.router, prefix="/api/connections", dependencies=protected)
    app.include_router(context.router, prefix="/api/context", dependencies=protected)
    app.include_router(query.router, prefix="/api/query", dependencies=protected)
    app.include_router(history.router, prefix="/api/history", dependencies=protected)
    app.include_router(sessions.router, prefix="/api/sessions", dependencies=protected)
    app.include_router(export.router, prefix="/api/export", dependencies=protected)
    app.include_router(settings_router.router, prefix="/api/settings", dependencies=protected)

    return app


app = create_app()
