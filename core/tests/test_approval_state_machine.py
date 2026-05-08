"""Approval state machine tests with the store mocked.

Covers legal and illegal transitions per spec §11.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any
from unittest.mock import AsyncMock

import pytest

from cockpit_core.agent.approvals import ApprovalManager, IllegalApprovalTransition
from cockpit_core.agent.contract import Tool


@pytest.fixture(autouse=True)
def patch_store(monkeypatch):
    """Replace the store + observability layers with in-memory fakes."""
    # state shared across the fakes
    state: dict[str, Any] = {"approvals": {}, "tool_calls": {}}

    async def fake_create(*, conversation_id, tool_call_id, timeout_seconds=60, conn=None):
        from datetime import UTC, datetime
        from uuid import uuid4

        from cockpit_core.store.approvals import Approval

        aid = str(uuid4())
        approval = Approval(
            id=aid,
            conversation_id=conversation_id,
            tool_call_id=tool_call_id,
            requested_at=datetime.now(UTC),
            resolved_at=None,
            decision=None,
            decided_by=None,
            decided_via=None,
            timeout_seconds=timeout_seconds,
        )
        state["approvals"][aid] = approval
        return approval

    async def fake_get(approval_id, *, conn=None):
        return state["approvals"].get(approval_id)

    async def fake_resolve(approval_id, *, decision, decided_by, decided_via, conn=None):
        from datetime import UTC, datetime

        from cockpit_core.store.approvals import Approval

        existing = state["approvals"].get(approval_id)
        if existing is None or existing.resolved_at is not None:
            return None
        new = Approval(
            id=existing.id,
            conversation_id=existing.conversation_id,
            tool_call_id=existing.tool_call_id,
            requested_at=existing.requested_at,
            resolved_at=datetime.now(UTC),
            decision=decision,
            decided_by=decided_by,
            decided_via=decided_via,
            timeout_seconds=existing.timeout_seconds,
        )
        state["approvals"][approval_id] = new
        return new

    async def fake_update_tool_call(*args, **kwargs):
        return None

    async def fake_publish(**_kwargs):
        return None

    monkeypatch.setattr("cockpit_core.agent.approvals.create_approval", fake_create)
    monkeypatch.setattr("cockpit_core.agent.approvals.get_approval", fake_get)
    monkeypatch.setattr("cockpit_core.agent.approvals.resolve_approval", fake_resolve)
    monkeypatch.setattr(
        "cockpit_core.agent.approvals.update_tool_call_status", fake_update_tool_call
    )
    monkeypatch.setattr("cockpit_core.agent.approvals.publish_approval", fake_publish)
    monkeypatch.setattr("cockpit_core.agent.approvals.emit", lambda **_: None)
    return state


def _tool(name: str, phrase: str = "go ahead") -> Tool:
    async def _h(_req, _ctx):
        return {"ok": True}

    return Tool(
        name=name,
        description="t",
        schema={"type": "object", "properties": {}, "required": []},
        blast_radius="dangerous",
        handler=_h,
        preamble=phrase,
    )


@pytest.mark.asyncio
async def test_voice_resolution_flows_back_to_waiter():
    mgr = ApprovalManager()
    tool = _tool("schedule_move", phrase="Reggie, do it")

    async def resolver(approval_id):
        await asyncio.sleep(0.05)
        await mgr.resolve(
            approval_id=approval_id, decision="approved",
            decided_by="reggie", decided_via="voice",
        )

    # kick off the request and resolve concurrently
    task = asyncio.create_task(
        mgr.request_and_wait(
            conversation_id="c1", tool_call_id="t1", tool=tool, timeout_seconds=2
        )
    )
    await asyncio.sleep(0.01)
    pending = mgr.pending_phrase("c1")
    assert pending is not None
    aid, phrase = pending
    assert phrase == "Reggie, do it"
    asyncio.create_task(resolver(aid))
    outcome = await task
    assert outcome == "approved"


@pytest.mark.asyncio
async def test_timeout_resolves_as_timeout():
    mgr = ApprovalManager()
    tool = _tool("dispatch_truck")
    outcome = await mgr.request_and_wait(
        conversation_id="c2", tool_call_id="t2", tool=tool, timeout_seconds=0
    )
    assert outcome == "timeout"


@pytest.mark.asyncio
async def test_double_resolve_is_illegal(patch_store):
    mgr = ApprovalManager()
    tool = _tool("schedule_move")
    task = asyncio.create_task(
        mgr.request_and_wait(
            conversation_id="c3", tool_call_id="t3", tool=tool, timeout_seconds=2
        )
    )
    await asyncio.sleep(0.01)
    pending = mgr.pending_phrase("c3")
    assert pending is not None
    aid, _ = pending
    await mgr.resolve(approval_id=aid, decision="approved", decided_by="r", decided_via="voice")
    with pytest.raises(IllegalApprovalTransition):
        await mgr.resolve(
            approval_id=aid, decision="denied", decided_by="r", decided_via="cockpit"
        )
    await task


@pytest.mark.asyncio
async def test_resolve_unknown_id_returns_false():
    mgr = ApprovalManager()
    ok = await mgr.resolve(
        approval_id="does-not-exist",
        decision="approved",
        decided_by="r",
        decided_via="cockpit",
    )
    assert ok is False
