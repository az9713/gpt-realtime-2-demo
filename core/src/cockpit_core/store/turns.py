"""Turn store: per-utterance/tool rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import asyncpg

from cockpit_core.store._helpers import acquire, new_uuid, release, utcnow

TurnRole = Literal["user", "agent", "tool", "system"]


@dataclass(frozen=True)
class Turn:
    id: str
    conversation_id: str
    role: TurnRole
    transcript: str | None
    audio_uri: str | None
    model: str | None
    latency_ms: int | None
    ts: datetime


def _row_to_turn(row: asyncpg.Record) -> Turn:
    return Turn(
        id=str(row["id"]),
        conversation_id=str(row["conversation_id"]),
        role=row["role"],
        transcript=row["transcript"],
        audio_uri=row["audio_uri"],
        model=row["model"],
        latency_ms=row["latency_ms"],
        ts=row["ts"],
    )


async def append_turn(
    *,
    conversation_id: str,
    role: TurnRole,
    transcript: str | None = None,
    audio_uri: str | None = None,
    model: str | None = None,
    latency_ms: int | None = None,
    ts: datetime | None = None,
    conn: asyncpg.Connection | None = None,
) -> Turn:
    tid = new_uuid()
    when = ts or utcnow()
    c, owned = await acquire(conn)
    try:
        row = await c.fetchrow(
            """
            INSERT INTO app.turns
                (id, conversation_id, role, transcript, audio_uri, model, latency_ms, ts)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
            """,
            tid,
            conversation_id,
            role,
            transcript,
            audio_uri,
            model,
            latency_ms,
            when,
        )
        assert row is not None
        return _row_to_turn(row)
    finally:
        await release(c, owned)


async def list_turns(
    conversation_id: str,
    *,
    conn: asyncpg.Connection | None = None,
) -> list[Turn]:
    c, owned = await acquire(conn)
    try:
        rows = await c.fetch(
            "SELECT * FROM app.turns WHERE conversation_id = $1 ORDER BY ts ASC",
            conversation_id,
        )
        return [_row_to_turn(r) for r in rows]
    finally:
        await release(c, owned)


async def update_turn_transcript(
    turn_id: str,
    *,
    transcript: str,
    conn: asyncpg.Connection | None = None,
) -> None:
    c, owned = await acquire(conn)
    try:
        await c.execute(
            "UPDATE app.turns SET transcript = $2 WHERE id = $1",
            turn_id,
            transcript,
        )
    finally:
        await release(c, owned)
