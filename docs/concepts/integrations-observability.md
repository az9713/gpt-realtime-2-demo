# Integrations & Observability — one dashboard for everything

> **OpenAI guide:** [Integrations & Observability](https://developers.openai.com/api/docs/guides/agents/integrations-observability)
> **Where it lands:** the trace pipeline + the cockpit's trace explorer.

---

## What "observability" means here

Three things at the same time:

1. **Live insight** — what is the agent doing *right now*?
2. **Historical record** — what did the agent do, when, and why?
3. **Cost accounting** — how much did this conversation cost in OpenAI tokens?

Voice agents are unusual in that **a single conversation can span
seconds of speaking + minutes of holding open a costly WebSocket**.
You need to see latency, cost, and decisions on the same timeline,
or you can't tell whether your agent is good.

This codebase puts all three on one page: `/conversations/<id>` in the
cockpit.

---

## The trace event — one event per decision

The unit of observability is a **trace event**: a row in
`app.trace_events` with:

| Column | Type | Purpose |
|---|---|---|
| `id` | uuid | Primary key |
| `conversation_id` | uuid | Which call this belongs to |
| `ts` | timestamptz | When it happened |
| `kind` | text | Event type (see below) |
| `payload_json` | jsonb | Event-specific data |
| `cost_usd` | numeric(10, 6) | Incremental cost (0 for most) |

The event kinds emitted by v1:

| `kind` | When |
|---|---|
| `session.start` | New conversation row created |
| `turn.user` | User finished speaking, transcript persisted |
| `turn.agent` | Agent finished speaking, transcript persisted |
| `tool.requested` | Dispatcher started executing a tool |
| `tool.executed` | Tool handler returned successfully |
| `tool.failed` | Tool handler raised |
| `tool.unknown` | Model called a tool name that isn't registered |
| `guardrail.passed` | Guardrails saw the tool call and let it through |
| `guardrail.blocked` | A guardrail blocked the tool call |
| `approval.requested` | A dangerous tool call created an approval row |
| `approval.resolved` | An approval was approved/denied/timed out |
| `mode.switch` | The session switched between realtime2 and translate |
| `session.end` | Conversation finalized |
| `post_call.failed` | Post-call hook raised |

Adding a new kind is a one-line code change (the column is free-text);
there's no enum to extend.

---

## Audit divergences (Phase 5)

For verticals that opt in via `pack.yaml: audit_transcripts: true`,
a separate observability table — `app.audit_divergences` — captures
mismatches between the agent's user-side transcript and the canonical
whisper transcript. This is **not** a trace event; trace events are
the per-step decision log, divergences are a derived analytical view
populated by a nightly batch job.

| Divergence kind | When |
|---|---|
| `paraphrase` | Small WER, both texts present (informational; usually unflagged below the 0.15 threshold) |
| `omission` | Agent's transcript has materially fewer tokens than canonical |
| `addition` | Agent's transcript has materially more tokens than canonical |
| `mismatch` | High WER (≥ 0.50) with similar token counts (likely hallucination) |

`make audit` runs the diff over the previous 24 hours of audit-flagged
conversations and persists divergences. The cockpit's `/audit` page
renders them. See [concepts/audit-transcripts.md](audit-transcripts.md)
for the full pipeline.

---

## Why async-batched writes

Naïve approach: every decision writes a row directly to Postgres.
Result: agent loop blocks on DB for milliseconds at a time, mounted
across hundreds of decisions per minute, latency budget gone.

What the cockpit does instead, in `core/src/cockpit_core/observability/tracer.py`:

```python
class Tracer:
    def emit(self, *, conversation_id, kind, payload=None, cost_usd=0):
        event = PendingTraceEvent(...)
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            logger.warning("trace_dropped", ...)
```

The `emit` call is non-blocking. It enqueues into a 10 000-event
asyncio Queue. A background task pulls from the queue and `INSERT`s
in batches of 50 (or every 500 ms, whichever comes first):

```python
async def _run(self):
    buffer = []
    while not self._stop.is_set():
        try:
            ev = await asyncio.wait_for(self._queue.get(), timeout=self._interval)
            buffer.append(ev)
        except TimeoutError:
            pass
        if buffer and (len(buffer) >= self._batch_size or self._stop.is_set()):
            await self._flush(buffer)
            buffer = []
```

This gets two properties:

- **No backpressure on the agent loop.** `emit()` is a memory write.
- **Bounded write amplification.** One INSERT per 50 events instead of
  per event, with sub-second latency for the cockpit to see them.

When the queue fills (which would only happen under sustained
overload), events are *dropped* with a counter rather than blocking.
You can rebuild lost trace events from `turns + tool_calls` if you
need to — the tracer's job is to *augment* the durable record, not
to *be* it.

The `/healthz` endpoint exposes the dropped counter so you can alert
on it.

---

## Pub/sub for live updates

The cockpit doesn't poll the trace_events table. It subscribes to
Redis pub/sub channels:

| Channel | Carries |
|---|---|
| `approvals` | All approval events across all sessions (for the global queue) |
| `session:<conversation_id>` | All events for one conversation |

When the dispatcher opens `/conversations/<id>`, the cockpit opens
a WebSocket to the core's `/v1/sessions/<id>/events` endpoint. The
core's WebSocket handler subscribes to `session:<id>` in Redis and
forwards every message to the connected client.

Tracing in the core (`emit`) writes to Postgres asynchronously
(durable). For events that need live broadcast, the relevant code path
*also* publishes to Redis (e.g. `publish_session_event(...)` in
`observability/notifier.py`). This dual write is fine because Redis is
an *index* over the durable Postgres rows, not a replacement.

---

## Cost accounting

OpenAI's `response.done` event includes a `usage` field with token
counts:

```json
{
  "type": "response.done",
  "response": {
    "id": "...",
    "usage": {
      "total_tokens": ...,
      "input_tokens": ...,
      "output_tokens": ...,
      "input_token_details": { "audio_tokens": ..., "text_tokens": ..., "cached_tokens": ... },
      "output_token_details": { "audio_tokens": ..., "text_tokens": ... }
    }
  }
}
```

For Realtime, audio tokens are the dominant cost. The pricing
breakdown is published by OpenAI (and shifts; check the latest):

| Token type | Approx 2026 GA pricing |
|---|---|
| Input audio | $32 / 1M tokens |
| Cached input audio | $0.40 / 1M tokens |
| Output audio | $64 / 1M tokens |
| Input text | $4 / 1M tokens |
| Output text | $16 / 1M tokens |

A multiplier table per (model, token_type) lives in the core (or could
be loaded from env config). On every `response.done`, the edge would
forward the usage block to the core, which computes incremental
cost_usd, emits a `response.done` trace event with cost, and updates
the conversation's running total.

v1 ships the *plumbing* for this — `cost_usd` columns exist, traces
have a cost field, the conversation row has a `cost_usd` total — but
the actual usage→price computation is a TODO marked at the seam. It's
a half-day of work to wire up properly per the current pricing.

---

## What the cockpit's trace explorer shows

`/conversations/<id>` page renders three columns:

```
┌─────────────────────────────┐    ┌────────────────────────────────┐
│  Trace                      │    │  Turns                         │
│  ───────                    │    │  ───────                       │
│  07:14:32  turn.user        │    │  USER                          │
│            "do you have..." │    │  Do you have a 440 volt       │
│  07:14:33  tool.requested   │    │  capacitor for a Carrier 58STA?│
│            parts_lookup     │    │                                │
│  07:14:33  guardrail.passed │    │  AGENT  · 1247 ms              │
│  07:14:33  tool.executed    │    │  We've got 12 of part         │
│  07:14:34  turn.agent       │    │  P-CAP-440-A in stock at      │
│            "we've got 12... │    │  $28.50 each. Want me to ...  │
│                             │    │                                │
└─────────────────────────────┘    └────────────────────────────────┘
```

Each row in the trace pane is colored by kind (read = green,
dangerous = orange, blocked = red, etc.). Clicking a row expands the
payload. The turns pane shows the conversational flow with role and
latency per agent turn.

A live session pulls in new events via the WebSocket; a past session
reads them once via REST.

---

## Replaying

Two operator scripts:

```bash
make replay CONV=<uuid>   # rehydrate a past conversation
make trace  CONV=<uuid>   # text dump of the trace timeline
```

`replay-conversation.py` interleaves turns and tool calls by timestamp
and prints them as a chronological story. Used for debugging "why did
the agent do X?" questions.

`trace-dump.py` is just `SELECT * FROM trace_events WHERE
conversation_id = X ORDER BY ts` printed nicely.

---

## Eval scores as a kind of observability

The vertical scenario evals (`make test-eval`) produce pass/fail per
scenario. CI surfaces these as a build-status check.

A scenario regression in CI is the *first* signal that something
broke. Production observability (the trace explorer) is the *second* —
once the regression hits prod and a real conversation surfaces it.

The cockpit's `make test-eval` runs in <30 s for the 8 HVAC scenarios
(scenarios 01-05 cover the realtime-2 conversational loop;
06 covers translate-bilingual; 07 covers notetaker; 08 covers
voicemail). Adding a new scenario takes about 10 minutes per the docs
in [eval-format.md](../eval-format.md). The cost-benefit on additional
evals is heavily in favor of adding them.

---

## Integrations: how external systems wire in

The platform doesn't ship integrations to specific products in v1.
What it ships are *seams*:

### 1. Tool handlers can call anything

`verticals/hvac/tools.py` reads JSON fixtures, but a real
`parts_lookup` could call a vendor's REST API:

```python
async def parts_lookup_handler(req, ctx):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{settings.parts_api_url}/search", params={
            "model": req.args.get("model_number"),
            "q": req.args.get("part_description"),
        }, headers={"Authorization": f"Bearer {settings.parts_api_token}"})
    r.raise_for_status()
    return {"matches": r.json()["results"]}
```

The agent infrastructure doesn't change. The tool gets slow → preamble
hides the latency. The tool fails → trace event records it.

### 2. The post_call hook for downstream notifications

`verticals/<name>/post_call.py` runs at end-of-conversation. The HVAC
implementation writes a JSON summary to `data/post-call/<conv_id>.json`.
Real deployments would replace this with a Slack message, an email,
a Webhook, a CRM ticket — whatever feeds the downstream workflow.

### 3. Trace sinks

`core/src/cockpit_core/observability/sinks.py` has a `TraceSink`
protocol with one method:

```python
class TraceSink(Protocol):
    async def write(self, events: list[PendingTraceEvent]) -> int: ...
```

v1 ships `PostgresSink` and `StdoutSink`. Adding an OTLP sink (for
Datadog / Honeycomb / Tempo) is ~30 lines: implement `write` to send a
batch of OTLP spans. The tracer doesn't care which sink it uses.

### 4. Webhooks out

The cockpit could expose `POST /v1/webhooks/<id>/trace` to push
trace events to an operator's webhook URL. The seam is the same
`TraceSink` plumbing. v1 doesn't ship this; nothing would fight you if
you added it.

---

## How to debug a sluggish agent

A latency walk-through:

1. Look at the trace for a recent conversation.
2. The horizontal axis is time; tool calls and turns appear as bars.
3. If `turn.user` → `tool.requested` is large (>1 s), the model is
   slow to plan. Likely cause: prompt too long, tool registry too
   large.
4. If `tool.requested` → `tool.executed` is large (>500 ms), the
   tool itself is slow. Cache or parallelize.
5. If `tool.executed` → `turn.agent` is large (>1 s), the model is
   slow to respond. Likely cause: tool result is huge or the prompt
   asked the model to summarize a lot.
6. If `turn.agent` rendering is slow on the cockpit, the issue is
   browser/network, not the agent.

The trace pane makes this visual without you having to run anything.

---

## Where to read next

- The data model itself: [realtime-conversations.md](realtime-conversations.md).
- The eval harness: [eval-format.md](../eval-format.md).
- Operator scripts: `scripts/replay-conversation.py`, `scripts/trace-dump.py`.
