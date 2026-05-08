import asyncio
from decimal import Decimal

import pytest

from cockpit_core.observability.tracer import Tracer
from cockpit_core.store.trace_events import PendingTraceEvent


class CollectSink:
    def __init__(self):
        self.batches: list[list[PendingTraceEvent]] = []

    async def write(self, events):
        self.batches.append(list(events))
        return len(events)


@pytest.mark.asyncio
async def test_batches_and_flushes():
    sink = CollectSink()
    tracer = Tracer(sink, batch_size=3, batch_interval_ms=100)
    await tracer.start()
    for i in range(5):
        tracer.emit(conversation_id="c", kind="x", payload={"i": i})
    await asyncio.sleep(0.4)
    await tracer.stop()
    flat = [e for batch in sink.batches for e in batch]
    assert len(flat) == 5
    assert tracer.dropped == 0


@pytest.mark.asyncio
async def test_drops_when_queue_full():
    sink = CollectSink()
    tracer = Tracer(sink, batch_size=10, batch_interval_ms=10_000, queue_size=2)
    # don't start the loop so flushes never happen
    for _ in range(5):
        tracer.emit(conversation_id="c", kind="x")
    assert tracer.dropped == 3


@pytest.mark.asyncio
async def test_stats_shape():
    sink = CollectSink()
    tracer = Tracer(sink, batch_size=1, batch_interval_ms=10)
    await tracer.start()
    tracer.emit(conversation_id="c", kind="x", cost_usd=Decimal("0.01"))
    await asyncio.sleep(0.05)
    await tracer.stop()
    s = tracer.stats()
    assert s["written"] == 1 and s["dropped"] == 0
