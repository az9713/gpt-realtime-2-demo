"""`make test-eval` entry point: discover scenarios and run them all."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from cockpit_core.eval.runner import run_scenario


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run scenario evals")
    parser.add_argument("--dir", default=None, help="root directory containing scenarios")
    parser.add_argument("--scenario", default=None, help="single scenario YAML to run")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[4]  # noqa: ASYNC240 — pure path math
    if args.scenario:
        paths = [Path(args.scenario)]
    else:
        root = Path(args.dir) if args.dir else repo_root / "verticals"
        paths = sorted(root.glob("*/scenarios/*.yaml"))

    if not paths:
        print("no scenarios found")
        return 0

    failed = 0
    for p in paths:
        result = await run_scenario(p)
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {p.relative_to(repo_root)} :: {result.scenario_id}")
        if not result.passed:
            failed += 1
            for f in result.failures:
                print(f"   - {f}")
    return failed


def run() -> None:
    rc = asyncio.run(main())
    sys.exit(rc)


if __name__ == "__main__":
    run()
