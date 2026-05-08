"""Post-call hook for HVAC. Writes a structured summary to disk.

Real-CRM integration is post-v1; v1 emits a JSON file the operator can
forward to whatever system they use.

Three summary shapes, one per session mode:
  • realtime2 / translate (default)  — full agent summary with job updates,
                                       parts orders, follow-ups
  • notetaker                        — transcript-only summary (no agent
                                       reasoning happened)
  • voicemail                        — caller's message + intent extraction
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from cockpit_core.agent.contract import SessionContext
from cockpit_core.store.tool_calls import list_tool_calls
from cockpit_core.store.turns import list_turns

POST_CALL_DIR = Path("/data/post-call")


async def post_call(ctx: SessionContext) -> None:
    POST_CALL_DIR.mkdir(parents=True, exist_ok=True)
    if ctx.mode == "notetaker":
        summary = await _notetaker_summary(ctx)
    elif ctx.mode == "voicemail":
        summary = await _voicemail_summary(ctx)
    else:
        summary = await _agent_summary(ctx)
    out = POST_CALL_DIR / f"{ctx.conversation_id}.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")


async def _agent_summary(ctx: SessionContext) -> dict[str, Any]:
    turns = await list_turns(ctx.conversation_id)
    tool_calls = await list_tool_calls(ctx.conversation_id)

    job_updates: list[dict[str, Any]] = []
    parts_orders: list[dict[str, Any]] = []
    follow_ups: list[str] = []
    for tc in tool_calls:
        if tc.tool_name in {"schedule_move", "dispatch_truck"} and tc.status == "executed":
            job_updates.append(
                {
                    "tool": tc.tool_name,
                    "args": tc.args_json,
                    "result": tc.result_json,
                    "at": tc.finished_at.isoformat() if tc.finished_at else None,
                }
            )
        if tc.tool_name == "parts_lookup" and tc.status == "executed":
            parts_orders.append({"args": tc.args_json, "result": tc.result_json})

    # Lightweight follow-up extraction: any user turn ending in "?" is a
    # candidate the dispatcher should review.
    for t in turns:
        if t.role == "user" and t.transcript and t.transcript.strip().endswith("?"):
            follow_ups.append(t.transcript)

    return {
        "kind": "agent",
        "conversation_id": ctx.conversation_id,
        "vertical": ctx.vertical,
        "surface": ctx.surface,
        "mode": ctx.mode,
        "ended_at": _now_iso(),
        "job_updates": job_updates,
        "parts_orders": parts_orders,
        "follow_ups": follow_ups,
        "tool_call_count": len(tool_calls),
        "turn_count": len(turns),
    }


async def _notetaker_summary(ctx: SessionContext) -> dict[str, Any]:
    """Notes-only: no agent reasoning happened. Emit the raw transcript so
    the dispatcher can read back what was captured."""
    turns = await list_turns(ctx.conversation_id)
    transcript_lines = [
        f"[{t.role}] {t.transcript.strip()}" for t in turns if t.transcript
    ]
    return {
        "kind": "notetaker",
        "conversation_id": ctx.conversation_id,
        "vertical": ctx.vertical,
        "surface": ctx.surface,
        "mode": ctx.mode,
        "ended_at": _now_iso(),
        "turn_count": len(turns),
        "transcript": "\n".join(transcript_lines),
    }


async def _voicemail_summary(ctx: SessionContext) -> dict[str, Any]:
    """Voicemail: caller leaves a message; we capture transcript + cheap
    regex-driven intent extraction to help the dispatcher triage."""
    turns = await list_turns(ctx.conversation_id)
    transcript = " ".join(
        t.transcript.strip() for t in turns if t.transcript and t.role in {"user", "system"}
    )
    intent = _classify_voicemail_intent(transcript)
    callback = _extract_callback_phone(transcript)
    return {
        "kind": "voicemail",
        "conversation_id": ctx.conversation_id,
        "vertical": ctx.vertical,
        "surface": ctx.surface,
        "mode": ctx.mode,
        "ended_at": _now_iso(),
        "transcript": transcript,
        "intent": intent,
        "callback_phone": callback,
        "turn_count": len(turns),
    }


_VOICEMAIL_INTENT_KEYWORDS: dict[str, list[str]] = {
    "schedule": ["schedule", "appointment", "reschedule", "move", "book"],
    "parts": ["part", "capacitor", "filter", "thermostat", "compressor"],
    "complaint": ["broken", "not working", "leak", "loud", "noise"],
    "warranty": ["warranty", "covered", "still under"],
}


def _classify_voicemail_intent(text: str) -> list[str]:
    if not text:
        return []
    lower = text.lower()
    found = [
        key for key, words in _VOICEMAIL_INTENT_KEYWORDS.items() if any(w in lower for w in words)
    ]
    return found or ["unknown"]


# US-style phone number; permissive
_PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?(\d{3})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})")


def _extract_callback_phone(text: str) -> str | None:
    m = _PHONE_RE.search(text or "")
    if not m:
        return None
    return f"+1{m.group(1)}{m.group(2)}{m.group(3)}"


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
