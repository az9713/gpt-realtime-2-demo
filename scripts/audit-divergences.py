"""Cron-friendly audit runner (Phase 5).

Scans recent conversations belonging to verticals that have
``audit_transcripts: true`` in their pack.yaml, computes the
divergence list per conversation, persists each divergence to
``app.audit_divergences``, and exits.

Usage:

    python scripts/audit-divergences.py            # last 24 hours
    python scripts/audit-divergences.py --hours 72 # arbitrary window
    python scripts/audit-divergences.py --vertical hvac --hours 1

Designed to run from host cron — no scheduler service, fits the
single-tenant docker-compose deploy.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core" / "src"))

from cockpit_core.db import close_pool, init_pool  # noqa: E402
from cockpit_core.observability.audit import compute_divergences  # noqa: E402
from cockpit_core.store.audit_divergences import insert_divergence  # noqa: E402
from cockpit_core.store.conversations import list_recent_conversations  # noqa: E402
from cockpit_core.verticals.loader import PackLoadError, load_vertical  # noqa: E402


async def _audit_flagged_verticals(verticals: list[str] | None) -> set[str]:
    """Return the set of vertical names where audit_transcripts is true."""
    out: set[str] = set()
    if verticals:
        candidates = list(verticals)
    else:
        candidates = ["hvac"]  # extend with a directory scan when more verticals exist
    for v in candidates:
        try:
            pack = load_vertical(v)
        except PackLoadError:
            continue
        if pack.audit_transcripts:
            out.add(pack.name)
    return out


async def run(*, hours: int, verticals: list[str] | None) -> int:
    await init_pool()
    try:
        flagged = await _audit_flagged_verticals(verticals)
        if not flagged:
            print(
                "no verticals with audit_transcripts=true; nothing to do "
                f"(checked: {verticals or ['hvac']})"
            )
            return 0
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        # Pull recent conversations; filter to flagged verticals + cutoff
        recent = await list_recent_conversations(limit=200)
        candidates = [
            c for c in recent if c.vertical in flagged and c.started_at >= cutoff
        ]
        total = 0
        for conv in candidates:
            divs = await compute_divergences(conv.id)
            for d in divs:
                await insert_divergence(
                    conversation_id=d.conversation_id,
                    agent_turn_id=d.agent_turn_id,
                    canonical_turn_id=d.canonical_turn_id,
                    kind=d.kind,
                    score=d.score,
                    agent_text=d.agent_text,
                    canonical_text=d.canonical_text,
                )
            total += len(divs)
            print(
                f"audit: conv {conv.id[:8]} ({conv.vertical}) "
                f"-> {len(divs)} divergence(s)"
            )
        print(f"audit: scanned {len(candidates)} conversation(s); flagged {total} divergence(s)")
        return 0
    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--vertical", action="append", help="restrict to these verticals")
    args = p.parse_args()
    rc = asyncio.run(run(hours=args.hours, verticals=args.vertical))
    sys.exit(rc)


if __name__ == "__main__":
    main()
