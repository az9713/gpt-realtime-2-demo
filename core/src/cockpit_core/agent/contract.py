"""Agent and Tool contracts (spec §6.1, §6.2)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

BlastRadius = Literal["read", "safe-write", "dangerous"]


@dataclass
class SessionContext:
    """Per-conversation context threaded through the agent runtime."""

    conversation_id: str
    vertical: str
    surface: Literal["browser", "phone"]
    mode: Literal["realtime2", "translate", "voicemail", "notetaker"]
    persona: str | None = None
    language: str | None = None
    customer_ref: dict[str, Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallRequest:
    conversation_id: str
    turn_id: str
    tool_name: str
    args: dict[str, Any]
    surface: Literal["browser", "phone"]
    vertical: str


@dataclass
class ToolCallResult:
    tool_call_id: str
    status: Literal["executed", "pending_approval", "failed", "denied"]
    result: Any | None = None
    error: str | None = None
    pending_approval_phrase: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    blast_radius: BlastRadius
    handler: Callable[[ToolCallRequest, SessionContext], Awaitable[Any]]
    preamble: str | None = None


class Guardrail(Protocol):
    name: str

    async def pre_call(self, ctx: SessionContext, transcript: str) -> str: ...
    async def post_call(self, ctx: SessionContext, transcript: str) -> str: ...


class Agent(Protocol):
    vertical: str
    persona: str
    tools: list[Tool]
    guardrails: list[Guardrail]

    async def on_session_start(self, ctx: SessionContext) -> None: ...
    async def on_session_end(self, ctx: SessionContext) -> None: ...
    async def on_tool_call(self, req: ToolCallRequest, ctx: SessionContext) -> ToolCallResult: ...
