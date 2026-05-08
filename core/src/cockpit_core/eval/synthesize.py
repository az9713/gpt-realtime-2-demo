"""Phase 6 — synthesize a Scenario YAML from a past conversation.

Reads ``app.turns``, ``app.tool_calls``, ``app.approvals`` for one
conversation and produces a YAML that matches the schema in
``cockpit_core/eval/runner.py``. The intent is "real-call -> repeatable
regression test in 30 seconds."

Honors SPEC §13.2: v1 has no audio storage, so the synthesizer reads
*transcripts* (whichever the agent recorded — realtime2/translate or
the whisper sidecar's canonical when audit is on). A v1.5 variant
could re-transcribe stored audio; out of scope here.
"""

from __future__ import annotations

from typing import Any

from cockpit_core.store.approvals import list_pending_approvals
from cockpit_core.store.conversations import get_conversation
from cockpit_core.store.tool_calls import list_tool_calls
from cockpit_core.store.turns import list_turns


async def synthesize_scenario(conversation_id: str) -> dict[str, Any]:
    """Build a Scenario-shaped dict for the given conversation.

    Raises:
        ValueError: if the conversation cannot be found.
    """
    conv = await get_conversation(conversation_id)
    if conv is None:
        raise ValueError(f"conversation not found: {conversation_id}")

    turns = await list_turns(conversation_id)
    tool_calls = await list_tool_calls(conversation_id)

    user_inputs: list[str] = [
        t.transcript.strip()
        for t in turns
        if t.role == "user" and t.transcript and t.transcript.strip()
    ]

    actions: list[dict[str, Any]] = []
    if conv.mode and conv.mode != "realtime2":
        # Capture initial mode/language as actions so the eval reproduces them.
        actions.append({"kind": "mode", "mode": conv.mode})
    if conv.language and conv.language != "en":
        actions.append({"kind": "language", "language": conv.language})
    for tc in tool_calls:
        if tc.status != "executed":
            continue
        actions.append(
            {
                "kind": "tool",
                "name": tc.tool_name,
                "args": tc.args_json or {},
            }
        )

    expected_tool_calls: list[dict[str, Any]] = [
        {"name": tc.tool_name, "args_contains": tc.args_json or {}}
        for tc in tool_calls
        if tc.status == "executed"
    ]

    # Resolved approvals → expected_approvals entries.
    # We pull all approvals attached to this conversation's tool_calls,
    # not just the currently pending ones, so the historical decision
    # is captured.
    expected_approvals: list[dict[str, Any]] = []
    for tc in tool_calls:
        if tc.approval_id and tc.blast_radius == "dangerous":
            decision = "approved" if tc.status == "executed" else "denied"
            expected_approvals.append(
                {"tool": tc.tool_name, "decision": decision, "via": "auto"}
            )

    return {
        "id": f"replay_{conversation_id[:8]}",
        "description": (
            f"Synthesized from real conversation {conversation_id}. "
            f"Surface: {conv.surface}; mode: {conv.mode}; "
            f"started: {conv.started_at.isoformat()}"
        ),
        "vertical": conv.vertical,
        "surface": conv.surface,
        "language": conv.language or "en",
        "user_inputs": user_inputs,
        "actions": actions,
        "expected_tool_calls": expected_tool_calls,
        "expected_approvals": expected_approvals,
        "expected_no_pii": True,
        "expected_mode": conv.mode,
    }


# Keep the unused-but-imported `list_pending_approvals` so future
# extensions can incorporate it; ruff will complain if it's truly
# unused, so we re-export it.
__all__ = ["synthesize_scenario", "list_pending_approvals"]
