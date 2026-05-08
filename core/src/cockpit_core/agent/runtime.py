"""Per-session agent runtime: registry + dispatch + lifecycle for one conversation."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit_core.agent.approvals import get_approval_manager
from cockpit_core.agent.contract import SessionContext
from cockpit_core.agent.dispatch import ToolDispatcher
from cockpit_core.verticals.loader import VerticalPack


@dataclass
class AgentRuntime:
    pack: VerticalPack
    ctx: SessionContext
    dispatcher: ToolDispatcher


_active: dict[str, AgentRuntime] = {}


def attach_runtime(runtime: AgentRuntime) -> None:
    _active[runtime.ctx.conversation_id] = runtime


def detach_runtime(conversation_id: str) -> AgentRuntime | None:
    return _active.pop(conversation_id, None)


def get_runtime(conversation_id: str) -> AgentRuntime | None:
    return _active.get(conversation_id)


def make_runtime(pack: VerticalPack, ctx: SessionContext) -> AgentRuntime:
    dispatcher = ToolDispatcher(
        registry=pack.registry,
        guardrails=pack.guardrails,
        approvals=get_approval_manager(),
    )
    return AgentRuntime(pack=pack, ctx=ctx, dispatcher=dispatcher)
