"""Healthcheck endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cockpit_core.db import get_pool
from cockpit_core.observability.tracer import tracer_stats
from cockpit_core.redis_client import get_redis

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    db_ok = False
    redis_ok = False
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    try:
        await get_redis().ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    stats = tracer_stats()
    status = "ok" if db_ok and redis_ok else "degraded"
    return {
        "status": status,
        "db": "ok" if db_ok else "down",
        "redis": "ok" if redis_ok else "down",
        "tracer": stats,
    }
