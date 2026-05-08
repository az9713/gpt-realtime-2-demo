"""Tool-call dispatch: guardrails → approval gating → handler execution."""

from __future__ import annotations

from cockpit_core.agent.approvals import ApprovalManager
from cockpit_core.agent.contract import (
    SessionContext,
    Tool,
    ToolCallRequest,
    ToolCallResult,
)
from cockpit_core.agent.registry import ToolRegistry, UnknownToolError
from cockpit_core.guardrails.middleware import GuardrailRunner
from cockpit_core.logging import get_logger
from cockpit_core.observability.tracer import emit
from cockpit_core.store.tool_calls import create_tool_call, update_tool_call_status
from cockpit_core.store.turns import append_turn

logger = get_logger("dispatch")


class ToolDispatcher:
    """Glue between an agent's tool registry, the guardrail layer, the
    approval manager, and persistence.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        guardrails: GuardrailRunner,
        approvals: ApprovalManager,
    ) -> None:
        self._registry = registry
        self._guardrails = guardrails
        self._approvals = approvals

    async def execute(self, req: ToolCallRequest, ctx: SessionContext) -> ToolCallResult:
        try:
            tool = self._registry.get(req.tool_name)
        except UnknownToolError:
            emit(
                conversation_id=req.conversation_id,
                kind="tool.unknown",
                payload={"tool": req.tool_name},
            )
            return ToolCallResult(
                tool_call_id="",
                status="failed",
                error=f"unknown tool: {req.tool_name}",
            )

        turn = await append_turn(
            conversation_id=req.conversation_id,
            role="tool",
            transcript=f"{tool.name}({req.args})",
        )
        tool_call = await create_tool_call(
            conversation_id=req.conversation_id,
            turn_id=turn.id,
            tool_name=tool.name,
            args=req.args,
            blast_radius=tool.blast_radius,
            status="requested",
        )
        emit(
            conversation_id=req.conversation_id,
            kind="tool.requested",
            payload={
                "tool": tool.name,
                "blast_radius": tool.blast_radius,
                "args": req.args,
                "tool_call_id": tool_call.id,
            },
        )

        guard = await self._guardrails.before_tool_call(ctx, tool, req)
        if guard.blocked:
            await update_tool_call_status(
                tool_call.id, status="failed", result={"blocked_by": guard.reason}, finished=True
            )
            emit(
                conversation_id=req.conversation_id,
                kind="guardrail.blocked",
                payload={"reason": guard.reason, "tool": tool.name},
            )
            return ToolCallResult(
                tool_call_id=tool_call.id,
                status="denied",
                error=guard.reason,
            )

        if tool.blast_radius == "dangerous":
            decision = await self._approvals.request_and_wait(
                conversation_id=req.conversation_id,
                tool_call_id=tool_call.id,
                tool=tool,
            )
            if decision != "approved":
                emit(
                    conversation_id=req.conversation_id,
                    kind="approval.resolved",
                    payload={"decision": decision, "tool": tool.name},
                )
                return ToolCallResult(
                    tool_call_id=tool_call.id,
                    status="denied",
                    error=f"approval {decision}",
                )
            emit(
                conversation_id=req.conversation_id,
                kind="approval.resolved",
                payload={"decision": "approved", "tool": tool.name},
            )

        return await self._run_handler(tool, req, ctx, tool_call.id)

    async def _run_handler(
        self,
        tool: Tool,
        req: ToolCallRequest,
        ctx: SessionContext,
        tool_call_id: str,
    ) -> ToolCallResult:
        try:
            result = await tool.handler(req, ctx)
        except Exception as e:
            logger.exception("tool_handler_failed", tool=tool.name)
            await update_tool_call_status(
                tool_call_id, status="failed", result={"error": str(e)}, finished=True
            )
            emit(
                conversation_id=req.conversation_id,
                kind="tool.failed",
                payload={"tool": tool.name, "error": str(e)},
            )
            return ToolCallResult(tool_call_id=tool_call_id, status="failed", error=str(e))

        await update_tool_call_status(
            tool_call_id, status="executed", result=result, finished=True
        )
        emit(
            conversation_id=req.conversation_id,
            kind="tool.executed",
            payload={"tool": tool.name, "result": result},
        )
        return ToolCallResult(tool_call_id=tool_call_id, status="executed", result=result)
