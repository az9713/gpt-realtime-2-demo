"""Conversation store: top-level rows tracking each session."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import asyncpg

from cockpit_core.store._helpers import (
    acquire,
    from_jsonb,
    jsonb,
    new_uuid,
    release,
    utcnow,
)


@dataclass(frozen=True)
class Conversation:
    id: str
    vertical: str
    surface: str
    mode: str
    language: str | None
    customer_ref: dict[str, Any] | None
    agent_persona: str | None
    started_at: datetime
    ended_at: datetime | None
    cost_usd: Decimal


def _row_to_conversation(row: asyncpg.Record) -> Conversation:
    return Conversation(
        id=str(row["id"]),
        vertical=row["vertical"],
        surface=row["surface"],
        mode=row["mode"],
        language=row["language"],
        customer_ref=from_jsonb(row["customer_ref"]),
        agent_persona=row["agent_persona"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        cost_usd=row["cost_usd"],
    )


async def create_conversation(
    *,
    vertical: str,
    surface: str,
    mode: str = "realtime2",
    language: str | None = None,
    customer_ref: dict[str, Any] | None = None,
    agent_persona: str | None = None,
    conn: asyncpg.Connection | None = None,
) -> Conversation:
    """Insert a new conversation row, return the persisted record."""
    cid = new_uuid()
    started = utcnow()
    c, owned = await acquire(conn)
    try:
        row = await c.fetchrow(
            """
            INSERT INTO app.conversations
                (id, vertical, surface, mode, language, customer_ref,
                 agent_persona, started_at, cost_usd)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, 0)
            RETURNING *
            """,
            cid,
            vertical,
            surface,
            mode,
            language,
            jsonb(customer_ref),
            agent_persona,
            started,
        )
        assert row is not None
        return _row_to_conversation(row)
    finally:
        await release(c, owned)


async def get_conversation(
    conversation_id: str,
    *,
    conn: asyncpg.Connection | None = None,
) -> Conversation | None:
    c, owned = await acquire(conn)
    try:
        row = await c.fetchrow(
            "SELECT * FROM app.conversations WHERE id = $1",
            conversation_id,
        )
        return _row_to_conversation(row) if row else None
    finally:
        await release(c, owned)


async def end_conversation(
    conversation_id: str,
    *,
    cost_usd: Decimal | float | None = None,
    conn: asyncpg.Connection | None = None,
) -> Conversation | None:
    """Mark a conversation ended; optionally update cost."""
    ended = utcnow()
    c, owned = await acquire(conn)
    try:
        if cost_usd is None:
            row = await c.fetchrow(
                """
                UPDATE app.conversations
                   SET ended_at = $2
                 WHERE id = $1
             RETURNING *
                """,
                conversation_id,
                ended,
            )
        else:
            row = await c.fetchrow(
                """
                UPDATE app.conversations
                   SET ended_at = $2, cost_usd = $3
                 WHERE id = $1
             RETURNING *
                """,
                conversation_id,
                ended,
                Decimal(str(cost_usd)),
            )
        return _row_to_conversation(row) if row else None
    finally:
        await release(c, owned)


async def update_conversation_mode(
    conversation_id: str,
    *,
    mode: str,
    conn: asyncpg.Connection | None = None,
) -> None:
    c, owned = await acquire(conn)
    try:
        await c.execute(
            "UPDATE app.conversations SET mode = $2 WHERE id = $1",
            conversation_id,
            mode,
        )
    finally:
        await release(c, owned)


async def update_conversation_language(
    conversation_id: str,
    *,
    language: str,
    conn: asyncpg.Connection | None = None,
) -> None:
    c, owned = await acquire(conn)
    try:
        await c.execute(
            "UPDATE app.conversations SET language = $2 WHERE id = $1",
            conversation_id,
            language,
        )
    finally:
        await release(c, owned)


async def list_recent_conversations(
    *,
    limit: int = 50,
    offset: int = 0,
    conn: asyncpg.Connection | None = None,
) -> list[Conversation]:
    c, owned = await acquire(conn)
    try:
        rows = await c.fetch(
            """
            SELECT * FROM app.conversations
            ORDER BY started_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
        return [_row_to_conversation(r) for r in rows]
    finally:
        await release(c, owned)
