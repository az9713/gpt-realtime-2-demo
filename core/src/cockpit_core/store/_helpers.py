"""Internal store helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from cockpit_core.db import get_pool


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid4())


def coerce_uuid(value: UUID | str) -> str:
    return str(value)


async def acquire(conn: asyncpg.Connection | None = None) -> tuple[asyncpg.Connection, bool]:
    """Acquire a connection. Returns (conn, owned)."""
    if conn is not None:
        return conn, False
    pool = get_pool()
    return await pool.acquire(), True


async def release(conn: asyncpg.Connection, owned: bool) -> None:
    if owned:
        pool = get_pool()
        await pool.release(conn)


def jsonb(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str)


def from_jsonb(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value
