"""Phase 5 — divergence diff between agent transcripts and canonical
whisper transcripts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cockpit_core.observability.audit import (
    DEFAULT_MISMATCH_THRESHOLD,
    DEFAULT_PARAPHRASE_THRESHOLD,
    classify_divergence,
    compute_divergences,
)
from cockpit_core.store.turns import Turn


def _turn(*, role: str, text: str, model: str | None, ts: datetime, tid: str) -> Turn:
    return Turn(
        id=tid,
        conversation_id="conv-audit",
        role=role,  # type: ignore[arg-type]
        transcript=text,
        audio_uri=None,
        model=model,
        latency_ms=None,
        ts=ts,
    )


def test_word_error_rate_identical_strings_returns_zero():
    kind, score = classify_divergence("hello there", "hello there")
    assert kind is None
    assert score == 0.0


def test_paraphrase_within_tolerance_is_unflagged():
    kind, score = classify_divergence(
        "hello there friend",
        "hello there my friend",
    )
    # 1 edit / 4 max-tokens = 0.25, just above the default 0.15. Bump
    # threshold to make this a paraphrase explicitly.
    kind2, _ = classify_divergence(
        "hello there friend",
        "hello there my friend",
        paraphrase_threshold=0.5,
    )
    assert kind2 is None


def test_omission_classified_when_agent_shorter():
    kind, _ = classify_divergence(
        "I need a capacitor",
        "I need a 440 volt capacitor for a Carrier 58STA",
    )
    assert kind == "omission"


def test_addition_classified_when_agent_longer():
    kind, _ = classify_divergence(
        "I need a 440 volt capacitor for a Carrier 58STA right away",
        "I need a capacitor",
    )
    assert kind == "addition"


def test_mismatch_at_high_distance():
    kind, score = classify_divergence(
        "completely different text here",
        "I need a capacitor",
    )
    assert kind == "mismatch"
    assert score >= DEFAULT_MISMATCH_THRESHOLD


def test_paraphrase_threshold_applied_consistently():
    # 0 edits = 0 score = unflagged
    kind, _ = classify_divergence("a b c", "a b c")
    assert kind is None
    # 1 edit / 3 = 0.33 — between paraphrase and mismatch defaults
    kind, score = classify_divergence("a b c", "a b d")
    assert kind == "paraphrase"
    assert DEFAULT_PARAPHRASE_THRESHOLD < score < DEFAULT_MISMATCH_THRESHOLD


@pytest.mark.asyncio
async def test_compute_divergences_pairs_turns_by_time(monkeypatch):
    base = datetime.now(UTC)
    turns = [
        _turn(
            role="user",
            text="agent heard this",
            model="gpt-realtime-2",
            ts=base,
            tid="t-agent-1",
        ),
        _turn(
            role="user",
            text="whisper heard this",
            model="whisper",
            ts=base + timedelta(milliseconds=120),
            tid="t-whisper-1",
        ),
    ]

    async def fake_list_turns(_conv_id, *, conn=None):
        return turns

    monkeypatch.setattr("cockpit_core.observability.audit.list_turns", fake_list_turns)

    divs = await compute_divergences("conv-audit")
    # The two strings differ enough to be classified as some kind of divergence.
    assert len(divs) == 1
    d = divs[0]
    assert d.agent_turn_id == "t-agent-1"
    assert d.canonical_turn_id == "t-whisper-1"
    assert d.agent_text == "agent heard this"
    assert d.canonical_text == "whisper heard this"


@pytest.mark.asyncio
async def test_compute_divergences_unmatched_canonical_becomes_omission(monkeypatch):
    base = datetime.now(UTC)
    # Whisper captured a turn the agent missed entirely
    turns = [
        _turn(
            role="user",
            text="whisper only",
            model="whisper",
            ts=base,
            tid="t-w-1",
        ),
    ]

    async def fake_list_turns(_conv_id, *, conn=None):
        return turns

    monkeypatch.setattr("cockpit_core.observability.audit.list_turns", fake_list_turns)

    divs = await compute_divergences("conv-audit")
    assert len(divs) == 1
    assert divs[0].kind == "omission"
    assert divs[0].agent_turn_id is None
    assert divs[0].canonical_turn_id == "t-w-1"


@pytest.mark.asyncio
async def test_compute_divergences_unmatched_agent_becomes_addition(monkeypatch):
    base = datetime.now(UTC)
    turns = [
        _turn(
            role="user",
            text="agent imagined this",
            model="gpt-realtime-2",
            ts=base,
            tid="t-a-1",
        ),
    ]

    async def fake_list_turns(_conv_id, *, conn=None):
        return turns

    monkeypatch.setattr("cockpit_core.observability.audit.list_turns", fake_list_turns)

    divs = await compute_divergences("conv-audit")
    assert len(divs) == 1
    assert divs[0].kind == "addition"
    assert divs[0].agent_turn_id == "t-a-1"
    assert divs[0].canonical_turn_id is None


@pytest.mark.asyncio
async def test_compute_divergences_clean_pair_returns_empty(monkeypatch):
    base = datetime.now(UTC)
    turns = [
        _turn(
            role="user",
            text="hi how can I help",
            model="gpt-realtime-2",
            ts=base,
            tid="t-a",
        ),
        _turn(
            role="user",
            text="hi how can I help",
            model="whisper",
            ts=base + timedelta(milliseconds=50),
            tid="t-w",
        ),
    ]

    async def fake_list_turns(_conv_id, *, conn=None):
        return turns

    monkeypatch.setattr("cockpit_core.observability.audit.list_turns", fake_list_turns)

    divs = await compute_divergences("conv-audit")
    assert divs == []
