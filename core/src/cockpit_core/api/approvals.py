"""Approval REST API: list pending, approve, deny."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cockpit_core.agent.approvals import IllegalApprovalTransition, get_approval_manager
from cockpit_core.store.approvals import list_pending_approvals
from cockpit_core.store.tool_calls import get_tool_call

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


class ResolveBody(BaseModel):
    decision: Literal["approved", "denied"]
    decided_by: str | None = None


@router.get("")
async def list_pending() -> dict[str, Any]:
    pending = await list_pending_approvals()
    out: list[dict[str, Any]] = []
    for a in pending:
        tc = await get_tool_call(a.tool_call_id)
        out.append(
            {
                "approval_id": a.id,
                "conversation_id": a.conversation_id,
                "tool_call_id": a.tool_call_id,
                "tool_name": tc.tool_name if tc else None,
                "args": tc.args_json if tc else None,
                "blast_radius": tc.blast_radius if tc else None,
                "requested_at": a.requested_at.isoformat(),
                "timeout_seconds": a.timeout_seconds,
            }
        )
    return {"approvals": out}


@router.post("/{approval_id}/resolve")
async def resolve(approval_id: str, body: ResolveBody) -> dict[str, Any]:
    manager = get_approval_manager()
    try:
        ok = await manager.resolve(
            approval_id=approval_id,
            decision=body.decision,
            decided_by=body.decided_by or "cockpit",
            decided_via="cockpit",
        )
    except IllegalApprovalTransition as e:
        raise HTTPException(409, str(e)) from e
    if not ok:
        raise HTTPException(404, "approval not found")
    return {"status": "ok", "approval_id": approval_id, "decision": body.decision}
