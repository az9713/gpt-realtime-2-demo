"""Rebuilds a past conversation in dev mode for debugging.

Reads `turns`, `tool_calls`, and `trace_events` for a given conversation
and prints a human-readable timeline. Does not re-execute tool handlers.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core" / "src"))

from cockpit_core.db import close_pool, init_pool  # noqa: E402
from cockpit_core.store.tool_calls import list_tool_calls  # noqa: E402
from cockpit_core.store.trace_events import list_trace_events  # noqa: E402
from cockpit_core.store.turns import list_turns  # noqa: E402


async def replay(conv_id: str) -> int:
    await init_pool()
    try:
        turns = await list_turns(conv_id)
        tools = await list_tool_calls(conv_id)
        events = await list_trace_events(conv_id)
        print(f"# replay {conv_id}")
        print(f"  {len(turns)} turns · {len(tools)} tool calls · {len(events)} trace events")
        print()
        # interleave by timestamp
        rows: list[tuple[str, str]] = []
        for t in turns:
            rows.append((t.ts.isoformat(), f"[{t.role:5}] {t.transcript or ''}"))
        for tc in tools:
            rows.append(
                (
                    tc.started_at.isoformat(),
                    f"[tool ] {tc.tool_name}({tc.args_json}) -> {tc.status}",
                )
            )
        rows.sort(key=lambda r: r[0])
        for ts, line in rows:
            print(f"{ts}  {line}")
        return 0
    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("conversation_id")
    args = p.parse_args()
    rc = asyncio.run(replay(args.conversation_id))
    sys.exit(rc)


if __name__ == "__main__":
    main()
