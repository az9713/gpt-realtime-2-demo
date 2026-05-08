"""Session lifecycle: create / end / mode-switch."""

from __future__ import annotations

from cockpit_core.agent.contract import SessionContext
from cockpit_core.observability.tracer import emit
from cockpit_core.store.conversations import (
    Conversation,
    create_conversation,
    end_conversation,
    update_conversation_mode,
)


async def begin_session(
    *,
    vertical: str,
    surface: str,
    mode: str = "realtime2",
    persona: str | None = None,
    language: str | None = None,
    customer_ref: dict[str, object] | None = None,
) -> tuple[Conversation, SessionContext]:
    conv = await create_conversation(
        vertical=vertical,
        surface=surface,
        mode=mode,
        language=language,
        customer_ref=customer_ref,
        agent_persona=persona,
    )
    ctx = SessionContext(
        conversation_id=conv.id,
        vertical=vertical,
        surface=surface,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        persona=persona,
        language=language,
        customer_ref=customer_ref,
    )
    emit(
        conversation_id=conv.id,
        kind="session.start",
        payload={"vertical": vertical, "surface": surface, "mode": mode, "persona": persona},
    )
    return conv, ctx


async def finish_session(conversation_id: str) -> None:
    await end_conversation(conversation_id)
    emit(conversation_id=conversation_id, kind="session.end", payload={})


async def switch_mode(conversation_id: str, *, mode: str) -> None:
    await update_conversation_mode(conversation_id, mode=mode)
    emit(conversation_id=conversation_id, kind="mode.switch", payload={"mode": mode})
