"""Post-call hook for HVAC. Writes a structured summary to disk.

Real-CRM integration is post-v1; v1 emits a JSON file the operator can
forward to whatever system they use.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from cockpit_core.agent.contract import SessionContext
from cockpit_core.store.tool_calls import list_tool_calls
from cockpit_core.store.turns import list_turns

POST_CALL_DIR = Path("/data/post-call")


async def post_call(ctx: SessionContext) -> None:
    POST_CALL_DIR.mkdir(parents=True, exist_ok=True)
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

    summary = {
        "conversation_id": ctx.conversation_id,
        "vertical": ctx.vertical,
        "surface": ctx.surface,
        "ended_at": datetime.utcnow().isoformat() + "Z",
        "job_updates": job_updates,
        "parts_orders": parts_orders,
        "follow_ups": follow_ups,
        "tool_call_count": len(tool_calls),
        "turn_count": len(turns),
    }
    out = POST_CALL_DIR / f"{ctx.conversation_id}.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
