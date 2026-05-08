"""FastAPI entrypoint for the agent core."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cockpit_core.api.approvals import router as approvals_router
from cockpit_core.api.conversations import router as conversations_router
from cockpit_core.api.health import router as health_router
from cockpit_core.api.sessions import router as sessions_router
from cockpit_core.api.verticals import router as verticals_router
from cockpit_core.db import close_pool, init_pool
from cockpit_core.logging import configure_logging, get_logger
from cockpit_core.observability.tracer import shutdown_tracer, start_tracer
from cockpit_core.redis_client import close_redis, get_redis
from cockpit_core.settings import get_settings


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger("cockpit_core.lifespan")
    await init_pool(settings)
    redis = get_redis(settings)
    try:
        await redis.ping()
    except Exception as e:
        logger.warning("redis_ping_failed", err=str(e))
    await start_tracer()
    logger.info("startup_complete", port=settings.core_port, vertical=settings.default_vertical)
    try:
        yield
    finally:
        await shutdown_tracer()
        await close_redis()
        await close_pool()
        logger.info("shutdown_complete")


def create_app() -> FastAPI:
    app = FastAPI(title="Voice Operations Cockpit — Agent Core", lifespan=_lifespan)
    app.include_router(health_router)
    app.include_router(sessions_router)
    app.include_router(conversations_router)
    app.include_router(approvals_router)
    app.include_router(verticals_router)
    return app


app = create_app()


def run() -> None:
    """Entry point for `cockpit-core` console script."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "cockpit_core.main:app",
        host="0.0.0.0",
        port=settings.core_port,
        log_level=settings.log_level,
    )
