"""Guardrail runner: pre-call, tool-call, post-call hook points."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from cockpit_core.agent.contract import SessionContext, Tool, ToolCallRequest
from cockpit_core.guardrails.pii import PIIRedactor
from cockpit_core.observability.tracer import emit

PreCallHook = Callable[[SessionContext, str], Awaitable[str]]
ToolCallHook = Callable[[SessionContext, Tool, ToolCallRequest], Awaitable["GuardrailDecision"]]
PostCallHook = Callable[[SessionContext, str], Awaitable[str]]


@dataclass
class GuardrailDecision:
    blocked: bool = False
    reason: str | None = None


class GuardrailRunner:
    """Runs configured hooks at the three boundaries.

    Hooks are pure async functions; they can mutate transcripts (pre/post
    call) or block tool calls (tool call).
    """

    def __init__(
        self,
        *,
        pre_hooks: list[PreCallHook] | None = None,
        tool_hooks: list[ToolCallHook] | None = None,
        post_hooks: list[PostCallHook] | None = None,
        pii: PIIRedactor | None = None,
    ) -> None:
        self._pre = pre_hooks or []
        self._tool = tool_hooks or []
        self._post = post_hooks or []
        self._pii = pii or PIIRedactor()

    async def before_user_input(self, ctx: SessionContext, text: str) -> str:
        out = text
        for hook in self._pre:
            out = await hook(ctx, out)
        return out

    async def before_tool_call(
        self,
        ctx: SessionContext,
        tool: Tool,
        req: ToolCallRequest,
    ) -> GuardrailDecision:
        for hook in self._tool:
            decision = await hook(ctx, tool, req)
            if decision.blocked:
                emit(
                    conversation_id=ctx.conversation_id,
                    kind="guardrail.blocked",
                    payload={"tool": tool.name, "reason": decision.reason},
                )
                return decision
        emit(
            conversation_id=ctx.conversation_id,
            kind="guardrail.passed",
            payload={"tool": tool.name},
        )
        return GuardrailDecision(blocked=False)

    async def after_agent_output(self, ctx: SessionContext, text: str) -> str:
        out = self._pii.redact(text)
        for hook in self._post:
            out = await hook(ctx, out)
        return out
