"""Trace sinks. Postgres is primary; stdout is a debug fallback."""

from __future__ import annotations

import json
from typing import Any, Protocol

from cockpit_core.logging import get_logger
from cockpit_core.store.trace_events import PendingTraceEvent, insert_trace_events


class TraceSink(Protocol):
    async def write(self, events: list[PendingTraceEvent]) -> int: ...


class PostgresSink:
    async def write(self, events: list[PendingTraceEvent]) -> int:
        return await insert_trace_events(events)


class StdoutSink:
    def __init__(self) -> None:
        self.log = get_logger("trace.stdout")

    async def write(self, events: list[PendingTraceEvent]) -> int:
        for e in events:
            self.log.info(
                "trace_event",
                conv=e.conversation_id,
                kind=e.kind,
                payload=e.payload,
                cost_usd=str(e.cost_usd),
            )
        return len(events)


def serialize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str)
