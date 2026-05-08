"""asyncpg connection pool wrapper."""

from __future__ import annotations

import asyncpg

from cockpit_core.settings import Settings, get_settings

_pool: asyncpg.Pool | None = None


async def init_pool(settings: Settings | None = None) -> asyncpg.Pool:
    """Create the global pool. Idempotent."""
    global _pool
    if _pool is not None:
        return _pool
    s = settings or get_settings()
    _pool = await asyncpg.create_pool(
        dsn=s.dsn,
        min_size=2,
        max_size=10,
        server_settings={"search_path": "app, public"},
    )
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized; call init_pool() at startup")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
