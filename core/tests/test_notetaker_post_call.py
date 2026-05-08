"""Verifies the post_call hook produces a notetaker-shaped summary
when ctx.mode == 'notetaker'. No tool roll-up; transcript-only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cockpit_core.agent.contract import SessionContext


@pytest.fixture
def hvac_post_call(monkeypatch, tmp_path: Path):
    """Return the hvac post_call function, with the output dir + store
    layer faked so we don't need a live database or write to /data."""
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    src = repo_root / "core" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    # Reset any cached vertical packs
    for k in list(sys.modules):
        if k == "verticals" or k.startswith("verticals."):
            del sys.modules[k]

    from cockpit_core.verticals.loader import load_vertical_from_path

    pack = load_vertical_from_path(repo_root / "verticals" / "hvac")

    # Redirect POST_CALL_DIR to tmp_path to avoid touching /data
    import verticals.hvac.post_call as hvac_post_call_mod  # type: ignore[import-not-found]

    monkeypatch.setattr(hvac_post_call_mod, "POST_CALL_DIR", tmp_path)
    return pack.post_call, tmp_path, hvac_post_call_mod


def _ctx(mode: str = "notetaker") -> SessionContext:
    return SessionContext(
        conversation_id="conv-nt",
        vertical="hvac",
        surface="browser",
        mode=mode,  # type: ignore[arg-type]
        persona=None,
    )


def _fake_turns(transcripts: list[tuple[str, str]]):
    """Build a sequence of (role, text) into Turn-shaped objects."""
    from datetime import UTC, datetime

    from cockpit_core.store.turns import Turn

    base = datetime.now(UTC)
    return [
        Turn(
            id=f"t-{i}",
            conversation_id="conv-nt",
            role=role,  # type: ignore[arg-type]
            transcript=text,
            audio_uri=None,
            model="whisper",
            latency_ms=None,
            ts=base,
        )
        for i, (role, text) in enumerate(transcripts)
    ]


@pytest.mark.asyncio
async def test_notetaker_summary_has_transcript_no_tool_rollup(monkeypatch, hvac_post_call):
    post_call, tmp, hvac_mod = hvac_post_call

    async def fake_list_turns(*_args, **_kwargs):
        return _fake_turns(
            [
                ("user", "Caller: my AC is making a humming noise."),
                ("agent", "Dispatcher: how long has it been doing that?"),
                ("user", "Started yesterday afternoon."),
            ]
        )

    async def fake_list_tool_calls(*_args, **_kwargs):
        return []

    monkeypatch.setattr(hvac_mod, "list_turns", fake_list_turns)
    monkeypatch.setattr(hvac_mod, "list_tool_calls", fake_list_tool_calls)

    await post_call(_ctx(mode="notetaker"))

    out = tmp / "conv-nt.json"
    assert out.exists()
    summary: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    assert summary["kind"] == "notetaker"
    assert summary["mode"] == "notetaker"
    assert summary["turn_count"] == 3
    # transcript present, joined, no tool roll-up keys
    assert "humming noise" in summary["transcript"]
    assert "Started yesterday" in summary["transcript"]
    assert "job_updates" not in summary
    assert "parts_orders" not in summary


@pytest.mark.asyncio
async def test_realtime2_summary_unchanged_for_existing_callers(monkeypatch, hvac_post_call):
    """Non-regression: realtime2 mode still produces the agent-shape summary."""
    post_call, tmp, hvac_mod = hvac_post_call

    async def fake_list_turns(*_args, **_kwargs):
        return _fake_turns(
            [
                ("user", "Do you have a 440 volt capacitor?"),
                ("agent", "Yes, P-CAP-440-A."),
            ]
        )

    async def fake_list_tool_calls(*_args, **_kwargs):
        return []

    monkeypatch.setattr(hvac_mod, "list_turns", fake_list_turns)
    monkeypatch.setattr(hvac_mod, "list_tool_calls", fake_list_tool_calls)

    await post_call(_ctx(mode="realtime2"))

    out = tmp / "conv-nt.json"
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["kind"] == "agent"
    # The original summary keys are still present
    assert "job_updates" in summary
    assert "parts_orders" in summary
    assert "follow_ups" in summary
    assert "tool_call_count" in summary
