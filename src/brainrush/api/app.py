"""FastAPI application factory. No secrets in logs or responses."""
from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from brainrush.api.auth import AuthError
from brainrush.api.deps import SessionDep
from brainrush.api.routes import router
from brainrush.config import Settings
from brainrush.db.errors import ConflictError, NotFoundError

log = logging.getLogger("brainrush.api")


def create_app(settings: Settings, session_factory) -> FastAPI:
    app = FastAPI(title="BrainRush API", version="0.1.0")
    app.state.settings = settings
    app.state.session_factory = session_factory

    origins = [
        o.strip() for o in (settings.API_CORS_ORIGINS or "").split(",") if o.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["X-Telegram-Init-Data", "Content-Type"],
            max_age=600,
        )

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        # Never log initData or headers; telegram id only when verified.
        log.info(
            "%s %s -> %s (%dms) user=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            getattr(request.state, "telegram_id", "-"),
        )
        return response

    @app.exception_handler(AuthError)
    async def auth_failed(request: Request, exc: AuthError):
        return JSONResponse(status_code=401, content={"detail": str(exc)})

    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict(request: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def bad_request(request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.error("unhandled API error", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    @app.get("/health")
    async def health(session: SessionDep) -> dict:
        """Lightweight liveness check. Verifies DB connectivity with SELECT 1."""
        try:
            await session.execute(text("SELECT 1"))
            return {"status": "ok"}
        except Exception:
            log.error("health check: database unreachable", exc_info=True)
            return JSONResponse(status_code=503, content={"status": "db_unreachable"})

    @app.get("/ready")
    async def ready(session: SessionDep) -> dict:
        """Readiness check: same as health for now (no optional services).

        Kept separate from /health so providers can distinguish liveness
        from readiness without optional-service failures removing healthy
        instances.
        """
        try:
            await session.execute(text("SELECT 1"))
            return {"status": "ready"}
        except Exception:
            log.error("readiness check: database unreachable", exc_info=True)
            return JSONResponse(status_code=503, content={"status": "db_unreachable"})

    app.include_router(router)

    if settings.ALLOW_DEV_AUTH:
        log.warning(
            "ALLOW_DEV_AUTH is enabled: mock dev identities accepted. "
            "NEVER enable in production."
        )
    return app
