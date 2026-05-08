"""Operator CLI for Phase 6 — turn a real conversation into a Scenario YAML.

    make synthesize-eval CONV=<uuid>
    # or directly:
    python scripts/synthesize-eval.py <uuid> [--out path/to/scenario.yaml]

Default output path: verticals/<vertical>/scenarios/<id>.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core" / "src"))

from cockpit_core.db import close_pool, init_pool  # noqa: E402
from cockpit_core.eval.synthesize import synthesize_scenario  # noqa: E402


async def run(conv_id: str, out_path: Path | None) -> int:
    await init_pool()
    try:
        scenario = await synthesize_scenario(conv_id)
        if out_path is None:
            out_path = (
                ROOT
                / "verticals"
                / str(scenario["vertical"])
                / "scenarios"
                / f"{scenario['id']}.yaml"
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            yaml.safe_dump(scenario, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        print(f"wrote scenario: {out_path}")
        return 0
    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("conversation_id")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    rc = asyncio.run(run(args.conversation_id, args.out))
    sys.exit(rc)


if __name__ == "__main__":
    main()
