"""Phase 6 — eval scenario synthesis from a past conversation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cockpit_core.eval.synthesize import synthesize_scenario
from cockpit_core.store.conversations import Conversation
from cockpit_core.store.tool_calls import ToolCall
from cockpit_core.store.turns import Turn


def _conv(**over):
    base = dict(
        id="conv-syn",
        vertical="hvac",
        surface="phone",
        mode="realtime2",
        language="en",
        customer_ref=None,
        agent_persona="Aria",
        started_at=datetime.now(UTC),
        ended_at=None,
        cost_usd=Decimal("0"),
    )
    base.update(over)
    return Conversation(**base)


def _turn(role: str, text: str) -> Turn:
    return Turn(
        id=f"t-{role}-{hash(text) & 0xFFFF}",
        conversation_id="conv-syn",
        role=role,  # type: ignore[arg-type]
        transcript=text,
        audio_uri=None,
        model=None,
        latency_ms=None,
        ts=datetime.now(UTC),
    )


def _tc(name: str, args: dict, status: str = "executed", blast: str = "read", approval=False):
    return ToolCall(
        id=f"tc-{name}",
        conversation_id="conv-syn",
        turn_id="t-anchor",
        tool_name=name,
        args_json=args,
        result_json={"ok": True},
        status=status,  # type: ignore[arg-type]
        blast_radius=blast,  # type: ignore[arg-type]
        approval_id="approval-1" if approval else None,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_synthesize_basic_shape(monkeypatch):
    conv = _conv()
    turns = [
        _turn("user", "do you have a 440 volt capacitor?"),
        _turn("agent", "yes — P-CAP-440-A."),
    ]
    tool_calls = [_tc("parts_lookup", {"part_description": "capacitor"})]

    async def fake_get(_id, *, conn=None):
        return conv

    async def fake_turns(_id, *, conn=None):
        return turns

    async def fake_tcs(_id, *, conn=None):
        return tool_calls

    monkeypatch.setattr("cockpit_core.eval.synthesize.get_conversation", fake_get)
    monkeypatch.setattr("cockpit_core.eval.synthesize.list_turns", fake_turns)
    monkeypatch.setattr("cockpit_core.eval.synthesize.list_tool_calls", fake_tcs)

    s = await synthesize_scenario("conv-syn")
    assert s["vertical"] == "hvac"
    assert s["surface"] == "phone"
    assert s["language"] == "en"
    assert s["user_inputs"] == ["do you have a 440 volt capacitor?"]
    assert s["actions"] == [
        {"kind": "tool", "name": "parts_lookup", "args": {"part_description": "capacitor"}}
    ]
    assert s["expected_tool_calls"] == [
        {"name": "parts_lookup", "args_contains": {"part_description": "capacitor"}}
    ]
    assert s["expected_approvals"] == []
    assert s["expected_mode"] == "realtime2"
    assert s["id"].startswith("replay_")


@pytest.mark.asyncio
async def test_synthesize_translate_session_emits_mode_action(monkeypatch):
    conv = _conv(mode="translate", language="es")
    turns = [_turn("user", "hola")]

    async def fake_get(_id, *, conn=None):
        return conv

    async def fake_turns(_id, *, conn=None):
        return turns

    async def fake_tcs(_id, *, conn=None):
        return []

    monkeypatch.setattr("cockpit_core.eval.synthesize.get_conversation", fake_get)
    monkeypatch.setattr("cockpit_core.eval.synthesize.list_turns", fake_turns)
    monkeypatch.setattr("cockpit_core.eval.synthesize.list_tool_calls", fake_tcs)

    s = await synthesize_scenario("conv-syn")
    assert {"kind": "mode", "mode": "translate"} in s["actions"]
    assert {"kind": "language", "language": "es"} in s["actions"]
    assert s["expected_mode"] == "translate"


@pytest.mark.asyncio
async def test_synthesize_dangerous_tool_records_approval(monkeypatch):
    conv = _conv()
    turns = [_turn("user", "move job J-5001 to ten am.")]
    tool_calls = [
        _tc(
            "schedule_move",
            {"job_id": "J-5001", "new_slot": "2026-05-08T10:00:00Z"},
            blast="dangerous",
            approval=True,
            status="executed",
        )
    ]

    async def fake_get(_id, *, conn=None):
        return conv

    async def fake_turns(_id, *, conn=None):
        return turns

    async def fake_tcs(_id, *, conn=None):
        return tool_calls

    monkeypatch.setattr("cockpit_core.eval.synthesize.get_conversation", fake_get)
    monkeypatch.setattr("cockpit_core.eval.synthesize.list_turns", fake_turns)
    monkeypatch.setattr("cockpit_core.eval.synthesize.list_tool_calls", fake_tcs)

    s = await synthesize_scenario("conv-syn")
    expected = {"tool": "schedule_move", "decision": "approved", "via": "auto"}
    assert expected in s["expected_approvals"]


@pytest.mark.asyncio
async def test_synthesize_unknown_conv_raises(monkeypatch):
    async def fake_get(_id, *, conn=None):
        return None

    monkeypatch.setattr("cockpit_core.eval.synthesize.get_conversation", fake_get)

    with pytest.raises(ValueError, match="not found"):
        await synthesize_scenario("does-not-exist")


@pytest.mark.asyncio
async def test_synthesized_scenario_runs_through_existing_runner(monkeypatch, tmp_path):
    """End-to-end: synthesize -> write yaml -> run_scenario passes."""
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240 — pure path math
    src = repo_root / "core" / "src"
    if str(src) not in sys.path:  # noqa: ASYNC240 — sync sys.path manipulation
        sys.path.insert(0, str(src))
    # ensure verticals namespace fresh
    for k in list(sys.modules):
        if k == "verticals" or k.startswith("verticals."):
            del sys.modules[k]

    # Use a real fixture path so the loader resolves the HVAC pack.
    work = tmp_path / "hvac"
    work.mkdir()
    src_fix = repo_root / "verticals" / "hvac" / "fixtures"
    for f in src_fix.iterdir():  # noqa: ASYNC240 — test setup, sync ok
        (work / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("HVAC_FIXTURE_DIR", str(work))

    conv = _conv()
    turns = [_turn("user", "do you have a 440 volt capacitor?")]
    tool_calls = [_tc("parts_lookup", {"part_description": "capacitor"})]

    async def fake_get(_id, *, conn=None):
        return conv

    async def fake_turns(_id, *, conn=None):
        return turns

    async def fake_tcs(_id, *, conn=None):
        return tool_calls

    monkeypatch.setattr("cockpit_core.eval.synthesize.get_conversation", fake_get)
    monkeypatch.setattr("cockpit_core.eval.synthesize.list_turns", fake_turns)
    monkeypatch.setattr("cockpit_core.eval.synthesize.list_tool_calls", fake_tcs)

    import yaml as _yaml

    from cockpit_core.eval.runner import run_scenario

    s = await synthesize_scenario("conv-syn")
    out = repo_root / "verticals" / "hvac" / "scenarios" / "_synthesized_test.yaml"
    out.write_text(_yaml.safe_dump(s, sort_keys=False), encoding="utf-8")
    try:
        result = await run_scenario(out)
        assert result.passed, result.failures
    finally:
        if out.exists():
            out.unlink()
