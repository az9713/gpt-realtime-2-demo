"""Session API: edge ↔ core protocol (spec §6.3) + per-session WebSocket."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from cockpit_core.agent.approvals import get_approval_manager
from cockpit_core.agent.contract import ToolCallRequest
from cockpit_core.agent.lifecycle import begin_session, finish_session, switch_mode
from cockpit_core.agent.runtime import (
    attach_runtime,
    detach_runtime,
    get_runtime,
    make_runtime,
)
from cockpit_core.logging import get_logger
from cockpit_core.observability.notifier import publish_session_event
from cockpit_core.observability.tracer import emit
from cockpit_core.redis_client import get_redis
from cockpit_core.settings import get_settings
from cockpit_core.store.turns import append_turn
from cockpit_core.verticals.loader import load_vertical

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])
logger = get_logger("api.sessions")


class CreateSessionBody(BaseModel):
    vertical: str | None = None
    surface: Literal["browser", "phone"]
    mode: Literal["realtime2", "translate", "voicemail", "notetaker"] = "realtime2"
    language: str | None = None
    customer_ref: dict[str, Any] | None = None


class CreateSessionResponse(BaseModel):
    conversation_id: str
    vertical: str
    surface: str
    mode: str
    persona: str
    prompt: str
    tools: list[dict[str, Any]]
    voice: str
    realtime_model: str
    translate_model: str
    auto_translate_non_english: bool


class ToolCallBody(BaseModel):
    turn_id: str | None = None
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolCallResponseModel(BaseModel):
    tool_call_id: str
    status: Literal["executed", "pending_approval", "failed", "denied"]
    result: Any | None = None
    error: str | None = None


class ModeSwitchBody(BaseModel):
    mode: Literal["realtime2", "translate"]


_AGENTLESS_MODES: frozenset[str] = frozenset({"voicemail", "notetaker"})


@router.post("", response_model=CreateSessionResponse)
async def create_session(body: CreateSessionBody) -> CreateSessionResponse:
    """Create a session. Two flavors:

    * **Agent modes** (``realtime2``, ``translate``) load the vertical pack's
      tool registry, attach a per-session ``AgentRuntime``, and return the
      full prompt + tools so the edge can configure the OpenAI Realtime WS.
    * **Agentless modes** (``voicemail``, ``notetaker``) skip the runtime —
      no tool dispatch, no agent persona. The conversation row is created
      so transcripts and traces still flow, but the edge opens a
      whisper-only ``TranscriptionSession`` rather than a ``RealtimeSession``.
    """
    settings = get_settings()
    vertical_name = body.vertical or settings.default_vertical
    pack = load_vertical(vertical_name)
    if body.surface not in pack.surfaces:
        raise HTTPException(
            400,
            f"vertical {pack.name!r} does not support surface {body.surface!r}",
        )
    if body.mode not in pack.modes:
        raise HTTPException(
            400,
            f"vertical {pack.name!r} does not support mode {body.mode!r}",
        )

    is_agentless = body.mode in _AGENTLESS_MODES
    persona = "" if is_agentless else pack.persona
    _, ctx = await begin_session(
        vertical=vertical_name,
        surface=body.surface,
        mode=body.mode,
        persona=persona or None,
        language=body.language,
        customer_ref=body.customer_ref,
    )
    if not is_agentless:
        runtime = make_runtime(pack, ctx)
        attach_runtime(runtime)

    return CreateSessionResponse(
        conversation_id=ctx.conversation_id,
        vertical=vertical_name,
        surface=body.surface,
        mode=body.mode,
        persona=persona,
        prompt="" if is_agentless else pack.prompt,
        tools=[] if is_agentless else pack.registry.schemas(),
        voice=settings.openai_voice,
        realtime_model=settings.openai_realtime_model,
        translate_model=settings.openai_translate_model,
        auto_translate_non_english=pack.auto_translate_non_english,
    )


@router.post("/{conversation_id}/tool-calls", response_model=ToolCallResponseModel)
async def post_tool_call(conversation_id: str, body: ToolCallBody) -> ToolCallResponseModel:
    runtime = get_runtime(conversation_id)
    if runtime is None:
        raise HTTPException(404, f"no active runtime for {conversation_id}")
    turn_id = body.turn_id
    if turn_id is None:
        # synthesize a turn marker for orphan tool calls
        from cockpit_core.store.turns import append_turn as _append

        turn = await _append(
            conversation_id=conversation_id,
            role="tool",
            transcript=f"{body.tool_name}({body.args})",
        )
        turn_id = turn.id
    req = ToolCallRequest(
        conversation_id=conversation_id,
        turn_id=turn_id,
        tool_name=body.tool_name,
        args=body.args,
        surface=runtime.ctx.surface,
        vertical=runtime.ctx.vertical,
    )
    result = await runtime.dispatcher.execute(req, runtime.ctx)
    return ToolCallResponseModel(
        tool_call_id=result.tool_call_id,
        status=result.status,
        result=result.result,
        error=result.error,
    )


@router.post("/{conversation_id}/end")
async def end_session(conversation_id: str) -> dict[str, str]:
    runtime = detach_runtime(conversation_id)
    if runtime is not None and runtime.pack.post_call is not None:
        try:
            await runtime.pack.post_call(runtime.ctx)
        except Exception as e:
            logger.exception("post_call_hook_failed", err=str(e), conv=conversation_id)
            emit(
                conversation_id=conversation_id,
                kind="post_call.failed",
                payload={"error": str(e)},
            )
    await finish_session(conversation_id)
    return {"status": "ok"}


@router.post("/{conversation_id}/mode")
async def post_mode_switch(conversation_id: str, body: ModeSwitchBody) -> dict[str, str]:
    if get_runtime(conversation_id) is None:
        raise HTTPException(404, f"no active runtime for {conversation_id}")
    await switch_mode(conversation_id, mode=body.mode)
    await publish_session_event(
        conversation_id=conversation_id,
        kind="mode.switch",
        payload={"mode": body.mode},
    )
    return {"status": "ok", "mode": body.mode}


@router.post("/{conversation_id}/transcript")
async def post_transcript(conversation_id: str, payload: dict[str, Any]) -> dict[str, str]:
    """Edge sends recognized transcript chunks here for persistence + tracing.

    `model` distinguishes which OpenAI model produced the transcript:
        - 'realtime2' / 'translate' — agent-side recognition
        - 'whisper'                 — gpt-realtime-whisper companion
    Used by Phase 2 (bilingual capture) and Phase 5 (audit transcripts).
    """
    role = payload.get("role", "user")
    text = payload.get("text", "")
    latency = payload.get("latency_ms")
    model = payload.get("model")
    if role not in {"user", "agent", "tool", "system"}:
        raise HTTPException(400, f"invalid role: {role}")
    turn = await append_turn(
        conversation_id=conversation_id,
        role=role,  # type: ignore[arg-type]
        transcript=text,
        latency_ms=latency,
        model=model,
    )
    emit(
        conversation_id=conversation_id,
        kind=f"turn.{role}",
        payload={"transcript_preview": text[:120], "turn_id": turn.id, "model": model},
    )
    await publish_session_event(
        conversation_id=conversation_id,
        kind="transcript",
        payload={"role": role, "text": text, "turn_id": turn.id, "model": model},
    )
    return {"status": "ok", "turn_id": turn.id}


@router.post("/{conversation_id}/approval-by-voice")
async def approval_by_voice(conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Edge calls this when the local voice-intent classifier matches an approval phrase."""
    phrase = str(payload.get("phrase", ""))
    manager = get_approval_manager()
    pending = manager.pending_phrase(conversation_id)
    if pending is None:
        return {"status": "noop", "reason": "no pending approval"}
    approval_id, expected = pending
    if expected and phrase.strip().lower() != expected.strip().lower():
        return {"status": "noop", "reason": "phrase mismatch"}
    resolved = await manager.resolve(
        approval_id=approval_id,
        decision="approved",
        decided_by="voice",
        decided_via="voice",
    )
    return {"status": "ok" if resolved else "noop", "approval_id": approval_id}


@router.websocket("/{conversation_id}/events")
async def events_ws(ws: WebSocket, conversation_id: str) -> None:
    """Per-session push channel: forwards Redis pub/sub frames to the edge."""
    await ws.accept()
    redis = get_redis()
    pubsub = redis.pubsub()
    channel = f"session:{conversation_id}"
    await pubsub.subscribe(channel)
    try:
        await ws.send_json({"kind": "session.attached", "conversation_id": conversation_id})
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                data = json.loads(message["data"])
            except (TypeError, ValueError):
                continue
            await ws.send_json(data)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
