"""Functional tests for the HVAC tool handlers against the JSON fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HVAC_DIR = REPO_ROOT / "verticals" / "hvac"


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path):
    src = REPO_ROOT / "core" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    # Each test gets its own writable copy of the fixtures so dangerous
    # tools mutate without polluting checked-in data.
    work = tmp_path / "hvac"
    work.mkdir()
    for f in (HVAC_DIR / "fixtures").iterdir():
        (work / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("HVAC_FIXTURE_DIR", str(work))
    for k in list(sys.modules):
        if k == "verticals" or k.startswith("verticals."):
            del sys.modules[k]
    yield


def _load_pack():
    from cockpit_core.verticals.loader import load_vertical_from_path

    return load_vertical_from_path(HVAC_DIR)


def _ctx():
    from cockpit_core.agent.contract import SessionContext

    return SessionContext(
        conversation_id="c1",
        vertical="hvac",
        surface="browser",
        mode="realtime2",
        persona="Aria",
    )


def _req(tool_name, args):
    from cockpit_core.agent.contract import ToolCallRequest

    return ToolCallRequest(
        conversation_id="c1",
        turn_id="t1",
        tool_name=tool_name,
        args=args,
        surface="browser",
        vertical="hvac",
    )


@pytest.mark.asyncio
async def test_parts_lookup_finds_capacitor():
    pack = _load_pack()
    handler = pack.registry.get("parts_lookup").handler
    out = await handler(_req("parts_lookup", {"part_description": "capacitor"}), _ctx())
    assert out["total_matches"] >= 2
    assert any("capacitor" in m["description"].lower() for m in out["matches"])


@pytest.mark.asyncio
async def test_warranty_check_returns_status():
    pack = _load_pack()
    handler = pack.registry.get("warranty_check").handler
    out = await handler(_req("warranty_check", {"unit_serial": "U-CARR-552204"}), _ctx())
    assert out["covered"] is True


@pytest.mark.asyncio
async def test_truck_inventory_unknown_truck():
    pack = _load_pack()
    handler = pack.registry.get("truck_inventory").handler
    out = await handler(_req("truck_inventory", {"truck_id": "T-999"}), _ctx())
    assert out["found"] is False


@pytest.mark.asyncio
async def test_schedule_move_mutates_job():
    pack = _load_pack()
    handler = pack.registry.get("schedule_move").handler
    out = await handler(
        _req("schedule_move", {"job_id": "J-5001", "new_slot": "2026-05-09T10:00:00Z"}),
        _ctx(),
    )
    assert out["ok"] is True
    assert out["job"]["scheduled_at"] == "2026-05-09T10:00:00Z"


@pytest.mark.asyncio
async def test_dispatch_truck_assigns():
    pack = _load_pack()
    handler = pack.registry.get("dispatch_truck").handler
    out = await handler(
        _req("dispatch_truck", {"job_id": "J-5002", "truck_id": "T-101"}),
        _ctx(),
    )
    assert out["ok"] is True
    assert out["job"]["assigned_truck"] == "T-101"
