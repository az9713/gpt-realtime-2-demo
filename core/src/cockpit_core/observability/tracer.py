"""Structured tracer with async batched writes and backpressure-drop."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from cockpit_core.logging import get_logger
from cockpit_core.observability.sinks import PostgresSink, TraceSink
from cockpit_core.settings import get_settings
from cockpit_core.store.trace_events import PendingTraceEvent

logger = get_logger("tracer")


class Tracer:
    """Async batched trace writer.

    Drops events with a counter when the queue is full, rather than
    blocking the agent loop. We can recover most state from
    `turns` + `tool_calls` if traces are lost.
    """

    def __init__(
        self,
        sink: TraceSink,
        *,
        batch_size: int = 50,
        batch_interval_ms: int = 500,
        queue_size: int = 10_000,
    ) -> None:
        self._sink = sink
        self._batch_size = batch_size
        self._interval = batch_interval_ms / 1000
        self._queue: asyncio.Queue[PendingTraceEvent] = asyncio.Queue(maxsize=queue_size)
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.dropped = 0
        self.written = 0

    def emit(
        self,
        *,
        conversation_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        cost_usd: Decimal | float | int = 0,
    ) -> None:
        event = PendingTraceEvent(
            conversation_id=conversation_id,
            kind=kind,
            payload=payload or {},
            cost_usd=Decimal(str(cost_usd)),
        )
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            logger.warning("trace_dropped", kind=kind, dropped_total=self.dropped)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="tracer-loop")

    async def _run(self) -> None:
        buffer: list[PendingTraceEvent] = []
        while not self._stop.is_set():
            try:
                ev = await asyncio.wait_for(self._queue.get(), timeout=self._interval)
                buffer.append(ev)
            except TimeoutError:
                pass
            if buffer and (len(buffer) >= self._batch_size or self._stop.is_set()):
                await self._flush(buffer)
                buffer = []
        if buffer:
            await self._flush(buffer)

    async def _flush(self, events: list[PendingTraceEvent]) -> None:
        try:
            written = await self._sink.write(events)
            self.written += written
        except Exception as e:
            self.dropped += len(events)
            logger.error("trace_flush_failed", err=str(e), batch=len(events))

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    def stats(self) -> dict[str, int]:
        return {
            "written": self.written,
            "dropped": self.dropped,
            "queue_depth": self._queue.qsize(),
        }


_tracer: Tracer | None = None


async def start_tracer(sink: TraceSink | None = None) -> Tracer:
    global _tracer
    if _tracer is not None:
        return _tracer
    s = get_settings()
    _tracer = Tracer(
        sink or PostgresSink(),
        batch_size=s.trace_batch_size,
        batch_interval_ms=s.trace_batch_interval_ms,
    )
    await _tracer.start()
    return _tracer


async def shutdown_tracer() -> None:
    global _tracer
    if _tracer is not None:
        await _tracer.stop()
        _tracer = None


def get_tracer() -> Tracer:
    if _tracer is None:
        raise RuntimeError("tracer not started; call start_tracer() at startup")
    return _tracer


def emit(
    *,
    conversation_id: str,
    kind: str,
    payload: dict[str, Any] | None = None,
    cost_usd: Decimal | float | int = 0,
) -> None:
    if _tracer is None:
        return
    _tracer.emit(
        conversation_id=conversation_id,
        kind=kind,
        payload=payload,
        cost_usd=cost_usd,
    )


def tracer_stats() -> dict[str, int]:
    if _tracer is None:
        return {"written": 0, "dropped": 0, "queue_depth": 0}
    return _tracer.stats()
