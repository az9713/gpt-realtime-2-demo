"""Phase 5 — read API for audit divergences."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from cockpit_core.store.audit_divergences import list_divergences

router = APIRouter(prefix="/v1/audits", tags=["audits"])


@router.get("/divergences")
async def list_audit_divergences(
    limit: int = Query(default=100, ge=1, le=500),
    conversation_id: str | None = Query(default=None),
) -> dict[str, Any]:
    rows = await list_divergences(conversation_id=conversation_id, limit=limit)
    return {
        "divergences": [
            {
                "id": r.id,
                "conversation_id": r.conversation_id,
                "agent_turn_id": r.agent_turn_id,
                "canonical_turn_id": r.canonical_turn_id,
                "kind": r.kind,
                "score": str(r.score),
                "agent_text": r.agent_text,
                "canonical_text": r.canonical_text,
                "flagged_at": r.flagged_at.isoformat(),
            }
            for r in rows
        ]
    }
