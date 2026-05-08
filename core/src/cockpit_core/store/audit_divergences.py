"""Persistence layer for app.audit_divergences (Phase 5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import asyncpg

from cockpit_core.store._helpers import acquire, new_uuid, release, utcnow


@dataclass(frozen=True)
class StoredDivergence:
    id: str
    conversation_id: str
    agent_turn_id: str | None
    canonical_turn_id: str | None
    kind: str
    score: Decimal
    agent_text: str | None
    canonical_text: str | None
    flagged_at: datetime


def _row_to_div(row: asyncpg.Record) -> StoredDivergence:
    return StoredDivergence(
        id=str(row["id"]),
        conversation_id=str(row["conversation_id"]),
        agent_turn_id=str(row["agent_turn_id"]) if row["agent_turn_id"] else None,
        canonical_turn_id=str(row["canonical_turn_id"]) if row["canonical_turn_id"] else None,
        kind=row["kind"],
        score=row["score"],
        agent_text=row["agent_text"],
        canonical_text=row["canonical_text"],
        flagged_at=row["flagged_at"],
    )


async def insert_divergence(
    *,
    conversation_id: str,
    agent_turn_id: str | None,
    canonical_turn_id: str | None,
    kind: str,
    score: float,
    agent_text: str | None,
    canonical_text: str | None,
    conn: asyncpg.Connection | None = None,
) -> StoredDivergence:
    did = new_uuid()
    flagged = utcnow()
    c, owned = await acquire(conn)
    try:
        row = await c.fetchrow(
            """
            INSERT INTO app.audit_divergences
                (id, conversation_id, agent_turn_id, canonical_turn_id,
                 kind, score, agent_text, canonical_text, flagged_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            did,
            conversation_id,
            agent_turn_id,
            canonical_turn_id,
            kind,
            Decimal(str(score)),
            agent_text,
            canonical_text,
            flagged,
        )
        assert row is not None
        return _row_to_div(row)
    finally:
        await release(c, owned)


async def list_divergences(
    *,
    conversation_id: str | None = None,
    limit: int = 100,
    conn: asyncpg.Connection | None = None,
) -> list[StoredDivergence]:
    c, owned = await acquire(conn)
    try:
        if conversation_id is None:
            rows = await c.fetch(
                """
                SELECT * FROM app.audit_divergences
                ORDER BY flagged_at DESC
                LIMIT $1
                """,
                limit,
            )
        else:
            rows = await c.fetch(
                """
                SELECT * FROM app.audit_divergences
                WHERE conversation_id = $1
                ORDER BY flagged_at DESC
                LIMIT $2
                """,
                conversation_id,
                limit,
            )
        return [_row_to_div(r) for r in rows]
    finally:
        await release(c, owned)
