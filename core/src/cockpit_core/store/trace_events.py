"""Trace event store. Async-batched writes."""

from __future__ import annotations

from dataclasses import dataclass, field
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
class TraceEvent:
    id: str
    conversation_id: str
    ts: datetime
    kind: str
    payload: dict[str, Any]
    cost_usd: Decimal


@dataclass
class PendingTraceEvent:
    """Pre-persisted shape used by the batched tracer."""

    conversation_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    cost_usd: Decimal = Decimal("0")
    ts: datetime = field(default_factory=utcnow)
    id: str = field(default_factory=new_uuid)


def _row_to_event(row: asyncpg.Record) -> TraceEvent:
    return TraceEvent(
        id=str(row["id"]),
        conversation_id=str(row["conversation_id"]),
        ts=row["ts"],
        kind=row["kind"],
        payload=from_jsonb(row["payload_json"]) or {},
        cost_usd=row["cost_usd"],
    )


async def insert_trace_events(
    events: list[PendingTraceEvent],
    *,
    conn: asyncpg.Connection | None = None,
) -> int:
    """Bulk insert via executemany. Returns count."""
    if not events:
        return 0
    c, owned = await acquire(conn)
    try:
        rows = [
            (
                e.id,
                e.conversation_id,
                e.ts,
                e.kind,
                jsonb(e.payload),
                e.cost_usd,
            )
            for e in events
        ]
        await c.executemany(
            """
            INSERT INTO app.trace_events
                (id, conversation_id, ts, kind, payload_json, cost_usd)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6)
            """,
            rows,
        )
        return len(events)
    finally:
        await release(c, owned)


async def list_trace_events(
    conversation_id: str,
    *,
    conn: asyncpg.Connection | None = None,
) -> list[TraceEvent]:
    c, owned = await acquire(conn)
    try:
        rows = await c.fetch(
            "SELECT * FROM app.trace_events WHERE conversation_id = $1 ORDER BY ts ASC",
            conversation_id,
        )
        return [_row_to_event(r) for r in rows]
    finally:
        await release(c, owned)
