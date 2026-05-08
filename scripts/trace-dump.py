"""Dumps the trace timeline for a conversation as readable text."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core" / "src"))

from cockpit_core.db import close_pool, init_pool  # noqa: E402
from cockpit_core.store.trace_events import list_trace_events  # noqa: E402


async def dump(conv_id: str) -> int:
    await init_pool()
    try:
        events = await list_trace_events(conv_id)
        for e in events:
            print(f"{e.ts.isoformat()}  {e.kind:24}  {e.payload}")
        return 0
    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("conversation_id")
    args = p.parse_args()
    rc = asyncio.run(dump(args.conversation_id))
    sys.exit(rc)


if __name__ == "__main__":
    main()
