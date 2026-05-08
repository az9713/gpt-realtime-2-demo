"""Approval store. Companion to tool_calls; one approval per dangerous call."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import asyncpg

from cockpit_core.store._helpers import acquire, new_uuid, release, utcnow

ApprovalDecision = Literal["approved", "denied", "timeout"]
ApprovalChannel = Literal["voice", "cockpit", "auto"]


@dataclass(frozen=True)
class Approval:
    id: str
    conversation_id: str
    tool_call_id: str
    requested_at: datetime
    resolved_at: datetime | None
    decision: ApprovalDecision | None
    decided_by: str | None
    decided_via: ApprovalChannel | None
    timeout_seconds: int


def _row_to_approval(row: asyncpg.Record) -> Approval:
    return Approval(
        id=str(row["id"]),
        conversation_id=str(row["conversation_id"]),
        tool_call_id=str(row["tool_call_id"]),
        requested_at=row["requested_at"],
        resolved_at=row["resolved_at"],
        decision=row["decision"],
        decided_by=row["decided_by"],
        decided_via=row["decided_via"],
        timeout_seconds=row["timeout_seconds"],
    )


async def create_approval(
    *,
    conversation_id: str,
    tool_call_id: str,
    timeout_seconds: int = 60,
    conn: asyncpg.Connection | None = None,
) -> Approval:
    aid = new_uuid()
    requested = utcnow()
    c, owned = await acquire(conn)
    try:
        row = await c.fetchrow(
            """
            INSERT INTO app.approvals
                (id, conversation_id, tool_call_id, requested_at, timeout_seconds)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            aid,
            conversation_id,
            tool_call_id,
            requested,
            timeout_seconds,
        )
        assert row is not None
        return _row_to_approval(row)
    finally:
        await release(c, owned)


async def get_approval(
    approval_id: str,
    *,
    conn: asyncpg.Connection | None = None,
) -> Approval | None:
    c, owned = await acquire(conn)
    try:
        row = await c.fetchrow(
            "SELECT * FROM app.approvals WHERE id = $1",
            approval_id,
        )
        return _row_to_approval(row) if row else None
    finally:
        await release(c, owned)


async def resolve_approval(
    approval_id: str,
    *,
    decision: ApprovalDecision,
    decided_by: str | None,
    decided_via: ApprovalChannel,
    conn: asyncpg.Connection | None = None,
) -> Approval | None:
    """Set decision atomically; only resolves rows that are still unresolved."""
    resolved = utcnow()
    c, owned = await acquire(conn)
    try:
        row = await c.fetchrow(
            """
            UPDATE app.approvals
               SET resolved_at = $2,
                   decision    = $3,
                   decided_by  = $4,
                   decided_via = $5
             WHERE id = $1 AND resolved_at IS NULL
         RETURNING *
            """,
            approval_id,
            resolved,
            decision,
            decided_by,
            decided_via,
        )
        return _row_to_approval(row) if row else None
    finally:
        await release(c, owned)


async def list_pending_approvals(
    *,
    conversation_id: str | None = None,
    conn: asyncpg.Connection | None = None,
) -> list[Approval]:
    c, owned = await acquire(conn)
    try:
        if conversation_id is None:
            rows = await c.fetch(
                """
                SELECT * FROM app.approvals
                 WHERE resolved_at IS NULL
                 ORDER BY requested_at ASC
                """
            )
        else:
            rows = await c.fetch(
                """
                SELECT * FROM app.approvals
                 WHERE resolved_at IS NULL AND conversation_id = $1
                 ORDER BY requested_at ASC
                """,
                conversation_id,
            )
        return [_row_to_approval(r) for r in rows]
    finally:
        await release(c, owned)
