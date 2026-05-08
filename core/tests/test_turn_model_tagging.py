"""Verifies turns can be persisted with model='whisper' alongside agent
turns from the same conversation — the data layer's contract for
Phase 2 (bilingual capture in translate) and Phase 5 (audit transcripts).

Uses an in-process fake of the asyncpg pool so we don't need a live
Postgres for this test.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from cockpit_core.store.turns import Turn


class FakeRecord:
    def __init__(self, **kwargs: Any) -> None:
        self._d = kwargs

    def __getitem__(self, k: str) -> Any:
        return self._d[k]


class FakeConn:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.rows: list[dict[str, Any]] = []

    async def fetchrow(self, sql: str, *args: Any) -> FakeRecord:
        self.executed.append((sql, args))
        # mirror the column order the INSERT uses
        record = {
            "id": args[0],
            "conversation_id": args[1],
            "role": args[2],
            "transcript": args[3],
            "audio_uri": args[4],
            "model": args[5],
            "latency_ms": args[6],
            "ts": args[7],
        }
        self.rows.append(record)
        return FakeRecord(**record)

    async def fetch(self, sql: str, *args: Any) -> list[FakeRecord]:
        return [FakeRecord(**r) for r in self.rows if r["conversation_id"] == args[0]]


@pytest.mark.asyncio
async def test_two_turns_same_conversation_different_models(monkeypatch):
    """Persist a translate-model turn and a whisper-model turn for the
    same conversation/user role. Round-trip must preserve `model`."""
    fake_conn = FakeConn()

    # Replace acquire/release with our fake.
    async def fake_acquire(conn=None):  # noqa: ANN001
        return fake_conn, False

    async def fake_release(_conn, _owned):
        return None

    monkeypatch.setattr("cockpit_core.store.turns.acquire", fake_acquire)
    monkeypatch.setattr("cockpit_core.store.turns.release", fake_release)

    from cockpit_core.store.turns import append_turn, list_turns

    t1 = await append_turn(
        conversation_id="conv-x",
        role="user",
        transcript="hola necesito agendar",
        model="gpt-realtime-translate",
    )
    t2 = await append_turn(
        conversation_id="conv-x",
        role="user",
        transcript="hola necesito agendar",
        model="whisper",
    )
    assert t1.model == "gpt-realtime-translate"
    assert t2.model == "whisper"

    rows = await list_turns("conv-x")
    models = {r.model for r in rows}
    assert models == {"gpt-realtime-translate", "whisper"}
    transcripts = {r.transcript for r in rows}
    # both rows have the same transcript text — they are the same utterance
    # captured by two different models
    assert transcripts == {"hola necesito agendar"}


@pytest.mark.asyncio
async def test_existing_callers_without_model_still_work(monkeypatch):
    """Backwards-compat: append_turn without `model` should still write a row
    (with NULL model). This is what every Phase-1-and-earlier caller uses."""
    fake_conn = FakeConn()

    async def fake_acquire(conn=None):  # noqa: ANN001
        return fake_conn, False

    async def fake_release(_conn, _owned):
        return None

    monkeypatch.setattr("cockpit_core.store.turns.acquire", fake_acquire)
    monkeypatch.setattr("cockpit_core.store.turns.release", fake_release)

    from cockpit_core.store.turns import append_turn

    t = await append_turn(
        conversation_id="conv-y",
        role="agent",
        transcript="how can I help?",
    )
    assert t.model is None
