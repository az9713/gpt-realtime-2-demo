# Realtime Conversations — shared session memory

> **OpenAI guide:** [Realtime Conversations](https://developers.openai.com/api/docs/guides/realtime-conversations)
> **Where it lands:** the conversation store. One ID, every surface,
> full history.

---

## The problem

A homeowner calls the HVAC company. They talk to Aria for two
minutes, identify the part they need, and say "let me check with my
husband, I'll call you back." They hang up.

Five minutes later, the dispatcher (looking at the cockpit) sees the
caller's name and address. The dispatcher presses Talk and says:
"Aria, what was the homeowner at 1402 Elm asking about?"

For Aria to answer correctly, the *cockpit conversation* must share
memory with the *phone conversation* that just ended. They're
different surfaces, different OpenAI WebSockets, possibly different
modes — but conceptually they're the same engagement.

That's what "shared session memory" means in this app: **conversation
state lives in Postgres, not in the model's session.** The model is
stateless from session to session. The platform reconstitutes context
when a new session starts.

---

## What OpenAI's session is and isn't

When the edge opens a WebSocket to OpenAI Realtime, OpenAI keeps an
in-memory conversation buffer for that WebSocket — every user message,
every assistant response, every function call. Sending
`response.create` makes the model generate a new turn against the
*entire* buffer.

That sounds like memory, but it has two problems:

1. It only lives until the WebSocket closes. Drop the connection,
   start over, and the model has forgotten everything.
2. It only covers *this* WebSocket. If the same conversation moved
   from a phone surface (one WebSocket) to the browser cockpit
   (another WebSocket), the second WebSocket starts blank.

So we treat OpenAI's session as **scratch memory only**, and we keep
the durable record ourselves.

---

## The two stores

```
┌────────────────────────────────────────────────────────┐
│  OpenAI session (scratch, ephemeral)                  │
│  ───────────────────────────────────                   │
│  • lives inside one WebSocket                          │
│  • holds the rolling user/assistant/function items     │
│  • discarded when the WS closes                        │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│  Postgres conversation store (durable, queryable)     │
│  ─────────────────────────────────────────────         │
│  • app.conversations     → one row per conversation;  │
│                              mode in {realtime2,       │
│                              translate, voicemail,     │
│                              notetaker}                 │
│  • app.turns             → utterances; turns.model     │
│                              tags whisper vs realtime  │
│  • app.tool_calls        → every tool invocation       │
│  • app.approvals         → every dangerous-tool gate   │
│  • app.trace_events      → every decision event        │
│  • app.audit_divergences → flagged transcript          │
│                              divergences (Phase 5;     │
│                              opt-in via vertical flag) │
└────────────────────────────────────────────────────────┘
```

The schema started as five tables ([`SPEC §5`](../../SPEC.md)); the
sixth (`audit_divergences`) was added by migration 0003 for the audit
transcripts feature. All tables are keyed by a UUIDv7 conversation ID
where applicable, which is sortable by creation time — a small but
useful detail for cockpit list views.

---

## The lifecycle

```
1. Surface arrives (phone or browser).

2. Edge → core: POST /v1/sessions
       core inserts app.conversations row,
       returns conversation_id + persona + prompt + tools + voice.

3. Edge opens an OpenAI Realtime WS,
       sends session.update with the prompt and tools.

4. As the conversation runs, the edge POSTs every recognized
   transcript chunk to core: POST /v1/sessions/{id}/transcript
       core inserts app.turns rows, emits trace events.

5. Tool calls flow: edge → core → tool handler → core writes
   app.tool_calls row → trace event → returns result → edge
   forwards to OpenAI.

6. Caller hangs up (or browser closes):
       Edge closes both WebSockets.
       Edge → core: POST /v1/sessions/{id}/end
       core sets app.conversations.ended_at,
       fires the vertical's post_call hook.
```

Every "decision boundary" in step 5 also writes a `trace_events` row.
That's how the cockpit's trace explorer reconstructs the timeline
later.

---

## Why this matters operationally

Three things become possible because state is durable:

### 1. Replay

```
$ make replay CONV=dfe17d59-e74b-4e17-906b-0a945704727a
# replay dfe17d59-e74b-4e17-906b-0a945704727a
  18 turns · 4 tool calls · 47 trace events

2026-05-08T07:14:32  [user ] Do you have a 440 volt capacitor for a Carrier 58STA?
2026-05-08T07:14:33  [tool ] parts_lookup({"part_description": "capacitor"}) -> executed
2026-05-08T07:14:34  [agent] We've got 12 of part P-CAP-440-A in stock at $28.50 each. ...
```

Built from `app.turns + app.tool_calls + app.trace_events`. No need
to remember which surface it ran on.

### 2. Cross-surface handoff

Two scenarios:

- **Resume.** A conversation ended, a new conversation starts, the
  agent prompt can include a "context summary" loaded from the recent
  prior conversation in `app.conversations`. v1 does not implement
  this automatically — it's a hook waiting for the spec to demand it
  — but every piece of data needed is in Postgres already.
- **Mid-call takeover.** A phone call is in progress; the dispatcher
  presses Talk in the cockpit. v1 routes them to a *different*
  session, but each side can subscribe to the other's per-session
  WebSocket events to follow along live (the cockpit already does
  this for trace events).

### 3. Audit and compliance

Healthcare, finance, and regulated industries need to be able to
answer "what did the agent say, what did it do, when, and on whose
authority?" This codebase answers all four:

- *what did it say* → `turns` (transcripts; `turns.model` tells you
  whether it was the agent's interpretation or whisper's canonical
  capture)
- *what did it do* → `tool_calls` (args, result, status)
- *when* → every row has a timestamp
- *on whose authority* → `approvals.decided_by`, `approvals.decided_via`
- *did the agent paraphrase, omit, or hallucinate* →
  `app.audit_divergences` (when the vertical opts into
  `audit_transcripts: true`; see
  [concepts/audit-transcripts.md](audit-transcripts.md))

---

## The schema, in one place

```sql
conversations (
  id              uuid pk,         -- UUIDv7
  vertical        text,
  surface         text,            -- 'browser' | 'phone'
  mode            text,            -- 'realtime2' | 'translate'
                                   --   | 'voicemail' | 'notetaker'
  language        text,            -- BCP-47, set after detect
  customer_ref    jsonb,
  agent_persona   text,
  started_at      timestamptz,
  ended_at        timestamptz,
  cost_usd        numeric(10, 4)
)

turns (
  id              uuid pk,
  conversation_id uuid fk,
  role            text,            -- 'user' | 'agent' | 'tool' | 'system'
  transcript      text,
  audio_uri       text,            -- reserved for future S3-style storage
  model           text,
  latency_ms      int,
  ts              timestamptz
)

tool_calls (
  id              uuid pk,
  conversation_id uuid fk,
  turn_id         uuid fk,
  tool_name       text,
  args_json       jsonb,
  result_json     jsonb,
  status          text,            -- 'requested' | 'approved' | 'denied' | 'executed' | 'failed'
  blast_radius    text,            -- 'read' | 'safe-write' | 'dangerous'
  approval_id     uuid,
  started_at      timestamptz,
  finished_at     timestamptz
)

approvals (
  id              uuid pk,
  conversation_id uuid fk,
  tool_call_id    uuid fk,
  requested_at    timestamptz,
  resolved_at     timestamptz,
  decision        text,            -- 'approved' | 'denied' | 'timeout'
  decided_by      text,
  decided_via     text,            -- 'voice' | 'cockpit' | 'auto'
  timeout_seconds int
)

trace_events (
  id              uuid pk,
  conversation_id uuid fk,
  ts              timestamptz,
  kind            text,            -- 'turn.user', 'tool.executed', 'approval.requested', ...
  payload_json    jsonb,
  cost_usd        numeric(10, 6)
)

audit_divergences (                  -- migration 0003 (Phase 5)
  id                 uuid pk,
  conversation_id    uuid fk,
  agent_turn_id      uuid,           -- nullable when the agent missed an utterance
  canonical_turn_id  uuid,           -- nullable when the agent imagined an utterance
  kind               text,           -- 'paraphrase' | 'omission' | 'addition' | 'mismatch'
  score              numeric(5, 4),  -- WER, normalized
  agent_text         text,
  canonical_text     text,
  flagged_at         timestamptz default now()
)
```

Migrations live in `core/alembic/versions/`. The initial migration
(`0001_initial`) creates the five core tables; `0002_widen_modes`
relaxed the conversations.mode CHECK to allow voicemail and
notetaker; `0003_audit_divergences` adds the audit table. All
forward-only, no destructive `down`.

---

## Persistence is async-batched, not blocking

Writing every transcript delta and trace event to Postgres on the hot
path would slow the agent loop. Instead:

- **Trace events** go through a batched async writer
  (`core/src/cockpit_core/observability/tracer.py`). Default: 50
  events per batch, 500 ms max latency, 10 000-event queue. If the
  queue fills (backpressure), events are dropped with a counter; the
  agent loop never blocks. We can rebuild lost traces from `turns +
  tool_calls` if we have to.
- **Turns** are written synchronously when the edge POSTs to
  `/v1/sessions/{id}/transcript`. The volume is one write per agent
  turn, not per audio frame.
- **Tool calls** and **approvals** are written synchronously by the
  dispatcher, with `BEGIN`/`COMMIT` semantics so race conditions
  between voice approval and cockpit click can't double-resolve.

---

## What's *not* in the schema (yet)

By design:

- **No raw audio.** v1 stores transcripts only. The `turns.audio_uri`
  column is reserved for an S3-compatible blob store later
  (e.g. for telehealth deployments where the audio is the audit
  trail). See [SPEC §13.2](../../SPEC.md#13-resolved-design-decisions).
- **No vector embeddings or "long-term memory."** Memory in v1 is
  *session-scoped recall via the prompt*. If a conversation needs to
  reference previous interactions, the calling code (or a future
  vertical hook) would summarize and inject into the prompt.

---

## How to look at it

```bash
# list recent conversations
curl -s http://localhost:8000/v1/conversations?limit=10 | jq

# detail
curl -s http://localhost:8000/v1/conversations/<id> | jq
curl -s http://localhost:8000/v1/conversations/<id>/turns | jq
curl -s http://localhost:8000/v1/conversations/<id>/tool-calls | jq
curl -s http://localhost:8000/v1/conversations/<id>/trace | jq

# operator scripts
make replay CONV=<uuid>
make trace  CONV=<uuid>
```

Or in the cockpit UI: `/conversations` lists them all, click any row to
see the full waterfall.
