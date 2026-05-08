"""Read API for the cockpit frontend."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from cockpit_core.store.conversations import get_conversation, list_recent_conversations
from cockpit_core.store.tool_calls import list_tool_calls
from cockpit_core.store.trace_events import list_trace_events
from cockpit_core.store.turns import list_turns

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


def _conv_dict(c: Any) -> dict[str, Any]:
    return {
        "id": c.id,
        "vertical": c.vertical,
        "surface": c.surface,
        "mode": c.mode,
        "language": c.language,
        "agent_persona": c.agent_persona,
        "started_at": c.started_at.isoformat(),
        "ended_at": c.ended_at.isoformat() if c.ended_at else None,
        "cost_usd": str(c.cost_usd),
    }


@router.get("")
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    rows = await list_recent_conversations(limit=limit, offset=offset)
    return {"conversations": [_conv_dict(c) for c in rows]}


@router.get("/{conversation_id}")
async def get_conversation_detail(conversation_id: str) -> dict[str, Any]:
    conv = await get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    return _conv_dict(conv)


@router.get("/{conversation_id}/turns")
async def turns(conversation_id: str) -> dict[str, Any]:
    rows = await list_turns(conversation_id)
    return {
        "turns": [
            {
                "id": t.id,
                "role": t.role,
                "transcript": t.transcript,
                "latency_ms": t.latency_ms,
                "ts": t.ts.isoformat(),
            }
            for t in rows
        ]
    }


@router.get("/{conversation_id}/tool-calls")
async def tool_calls(conversation_id: str) -> dict[str, Any]:
    rows = await list_tool_calls(conversation_id)
    return {
        "tool_calls": [
            {
                "id": r.id,
                "tool_name": r.tool_name,
                "blast_radius": r.blast_radius,
                "status": r.status,
                "args": r.args_json,
                "result": r.result_json,
                "approval_id": r.approval_id,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ]
    }


@router.get("/{conversation_id}/trace")
async def trace(conversation_id: str) -> dict[str, Any]:
    rows = await list_trace_events(conversation_id)
    return {
        "events": [
            {
                "id": e.id,
                "ts": e.ts.isoformat(),
                "kind": e.kind,
                "payload": e.payload,
                "cost_usd": str(e.cost_usd),
            }
            for e in rows
        ]
    }
