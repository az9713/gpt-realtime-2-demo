"""Tool call store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import asyncpg

from cockpit_core.store._helpers import (
    acquire,
    from_jsonb,
    jsonb,
    new_uuid,
    release,
    utcnow,
)

ToolCallStatus = Literal["requested", "approved", "denied", "executed", "failed"]
BlastRadius = Literal["read", "safe-write", "dangerous"]


@dataclass(frozen=True)
class ToolCall:
    id: str
    conversation_id: str
    turn_id: str
    tool_name: str
    args_json: dict[str, Any]
    result_json: Any | None
    status: ToolCallStatus
    blast_radius: BlastRadius
    approval_id: str | None
    started_at: datetime
    finished_at: datetime | None


def _row_to_tool_call(row: asyncpg.Record) -> ToolCall:
    return ToolCall(
        id=str(row["id"]),
        conversation_id=str(row["conversation_id"]),
        turn_id=str(row["turn_id"]),
        tool_name=row["tool_name"],
        args_json=from_jsonb(row["args_json"]) or {},
        result_json=from_jsonb(row["result_json"]),
        status=row["status"],
        blast_radius=row["blast_radius"],
        approval_id=str(row["approval_id"]) if row["approval_id"] else None,
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


async def create_tool_call(
    *,
    conversation_id: str,
    turn_id: str,
    tool_name: str,
    args: dict[str, Any],
    blast_radius: BlastRadius,
    status: ToolCallStatus = "requested",
    conn: asyncpg.Connection | None = None,
) -> ToolCall:
    tcid = new_uuid()
    started = utcnow()
    c, owned = await acquire(conn)
    try:
        row = await c.fetchrow(
            """
            INSERT INTO app.tool_calls
                (id, conversation_id, turn_id, tool_name, args_json,
                 status, blast_radius, started_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
            RETURNING *
            """,
            tcid,
            conversation_id,
            turn_id,
            tool_name,
            jsonb(args),
            status,
            blast_radius,
            started,
        )
        assert row is not None
        return _row_to_tool_call(row)
    finally:
        await release(c, owned)


async def get_tool_call(
    tool_call_id: str,
    *,
    conn: asyncpg.Connection | None = None,
) -> ToolCall | None:
    c, owned = await acquire(conn)
    try:
        row = await c.fetchrow(
            "SELECT * FROM app.tool_calls WHERE id = $1",
            tool_call_id,
        )
        return _row_to_tool_call(row) if row else None
    finally:
        await release(c, owned)


async def update_tool_call_status(
    tool_call_id: str,
    *,
    status: ToolCallStatus,
    result: Any | None = None,
    approval_id: str | None = None,
    finished: bool = False,
    conn: asyncpg.Connection | None = None,
) -> ToolCall | None:
    finished_at = utcnow() if finished else None
    c, owned = await acquire(conn)
    try:
        row = await c.fetchrow(
            """
            UPDATE app.tool_calls
               SET status = $2,
                   result_json = COALESCE($3::jsonb, result_json),
                   approval_id = COALESCE($4, approval_id),
                   finished_at = COALESCE($5, finished_at)
             WHERE id = $1
         RETURNING *
            """,
            tool_call_id,
            status,
            jsonb(result),
            approval_id,
            finished_at,
        )
        return _row_to_tool_call(row) if row else None
    finally:
        await release(c, owned)


async def list_tool_calls(
    conversation_id: str,
    *,
    conn: asyncpg.Connection | None = None,
) -> list[ToolCall]:
    c, owned = await acquire(conn)
    try:
        rows = await c.fetch(
            """
            SELECT * FROM app.tool_calls
             WHERE conversation_id = $1
             ORDER BY started_at ASC
            """,
            conversation_id,
        )
        return [_row_to_tool_call(r) for r in rows]
    finally:
        await release(c, owned)
