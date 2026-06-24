"""Approval state machine + per-session pending tracker."""

from __future__ import annotations

import asyncio
from typing import Literal

from cockpit_core.agent.contract import Tool
from cockpit_core.logging import get_logger
from cockpit_core.observability.notifier import publish_approval
from cockpit_core.observability.tracer import emit
from cockpit_core.store.approvals import (
    ApprovalChannel,
    ApprovalDecision,
    create_approval,
    get_approval,
    resolve_approval,
)
from cockpit_core.store.tool_calls import update_tool_call_status

logger = get_logger("approvals")

Outcome = Literal["approved", "denied", "timeout"]

VALID_TRANSITIONS: dict[str | None, set[ApprovalDecision]] = {
    None: {"approved", "denied", "timeout"},
}


class IllegalApprovalTransition(RuntimeError):  # noqa: N818 — name reads as a noun-phrase event
    pass


class ApprovalManager:
    """Tracks pending approvals per session and exposes resolution APIs."""

    def __init__(self) -> None:
        self._waiters: dict[str, asyncio.Future[ApprovalDecision]] = {}
        self._pending_by_conversation: dict[str, list[str]] = {}
        self._phrases: dict[str, str] = {}

    def pending_phrase(self, conversation_id: str) -> tuple[str, str] | None:
        """Most recently requested pending tool's (approval_id, phrase) for the session."""
        ids = self._pending_by_conversation.get(conversation_id, [])
        if not ids:
            return None
        approval_id = ids[-1]
        phrase = self._phrases.get(approval_id, "")
        return approval_id, phrase

    async def request_and_wait(
        self,
        *,
        conversation_id: str,
        tool_call_id: str,
        tool: Tool,
        timeout_seconds: int = 60,
    ) -> Outcome:
        approval = await create_approval(
            conversation_id=conversation_id,
            tool_call_id=tool_call_id,
            timeout_seconds=timeout_seconds,
        )
        await update_tool_call_status(tool_call_id, status="requested", approval_id=approval.id)
        phrase = (tool.preamble or "").strip()
        self._phrases[approval.id] = phrase
        self._pending_by_conversation.setdefault(conversation_id, []).append(approval.id)

        emit(
            conversation_id=conversation_id,
            kind="approval.requested",
            payload={
                "approval_id": approval.id,
                "tool": tool.name,
                "phrase": phrase,
                "timeout_seconds": timeout_seconds,
            },
        )
        await publish_approval(
            kind="approval.requested",
            conversation_id=conversation_id,
            payload={"approval_id": approval.id, "tool": tool.name, "phrase": phrase},
        )

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[ApprovalDecision] = loop.create_future()
        self._waiters[approval.id] = fut

        try:
            decision = await asyncio.wait_for(fut, timeout=timeout_seconds)
        except TimeoutError:
            await self._resolve(
                approval.id,
                conversation_id,
                tool_call_id,
                decision="timeout",
                decided_by=None,
                decided_via="auto",
            )
            return "timeout"
        finally:
            self._waiters.pop(approval.id, None)
            self._pending_by_conversation.get(conversation_id, []).remove(approval.id) if (
                approval.id in self._pending_by_conversation.get(conversation_id, [])
            ) else None

        new_status: Literal["approved", "denied"] = (
            "approved" if decision == "approved" else "denied"
        )
        await update_tool_call_status(tool_call_id, status=new_status)
        return decision

    async def resolve(
        self,
        *,
        approval_id: str,
        decision: ApprovalDecision,
        decided_by: str | None,
        decided_via: ApprovalChannel,
    ) -> bool:
        existing = await get_approval(approval_id)
        if existing is None:
            return False
        if existing.resolved_at is not None:
            raise IllegalApprovalTransition(
                f"approval {approval_id} already resolved as {existing.decision}"
            )
        return await self._resolve(
            approval_id,
            existing.conversation_id,
            existing.tool_call_id,
            decision=decision,
            decided_by=decided_by,
            decided_via=decided_via,
        )

    async def _resolve(
        self,
        approval_id: str,
        conversation_id: str,
        tool_call_id: str,
        *,
        decision: ApprovalDecision,
        decided_by: str | None,
        decided_via: ApprovalChannel,
    ) -> bool:
        row = await resolve_approval(
            approval_id,
            decision=decision,
            decided_by=decided_by,
            decided_via=decided_via,
        )
        if row is None:
            return False
        emit(
            conversation_id=conversation_id,
            kind="approval.resolved",
            payload={
                "approval_id": approval_id,
                "decision": decision,
                "decided_by": decided_by,
                "decided_via": decided_via,
            },
        )
        await publish_approval(
            kind="approval.resolved",
            conversation_id=conversation_id,
            payload={
                "approval_id": approval_id,
                "tool_call_id": tool_call_id,
                "decision": decision,
                "decided_via": decided_via,
            },
        )
        fut = self._waiters.get(approval_id)
        if fut is not None and not fut.done():
            fut.set_result(decision)
        self._phrases.pop(approval_id, None)
        return True


_manager: ApprovalManager | None = None


def get_approval_manager() -> ApprovalManager:
    global _manager
    if _manager is None:
        _manager = ApprovalManager()
    return _manager
