"""Runs the five HVAC scenarios end-to-end via the eval harness."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = sorted((REPO_ROOT / "verticals" / "hvac" / "scenarios").glob("*.yaml"))


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path):
    src = REPO_ROOT / "core" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    work = tmp_path / "hvac"
    work.mkdir()
    src_fix = REPO_ROOT / "verticals" / "hvac" / "fixtures"
    for f in src_fix.iterdir():
        (work / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("HVAC_FIXTURE_DIR", str(work))
    for k in list(sys.modules):
        if k == "verticals" or k.startswith("verticals."):
            del sys.modules[k]
    yield


@pytest.mark.parametrize("scenario_path", SCENARIOS, ids=lambda p: p.stem)
@pytest.mark.asyncio
async def test_scenario_passes(scenario_path):
    from cockpit_core.eval.runner import run_scenario

    result = await run_scenario(scenario_path)
    assert result.passed, f"{result.scenario_id}: {result.failures}"
