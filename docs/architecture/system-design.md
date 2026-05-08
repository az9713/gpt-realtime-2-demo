# System Design

The system at a glance, the boundaries between services, and the key
decisions that shaped the design.

---

## The big picture

```
                ┌─────────────────────────────────────────────┐
                │         Cockpit Frontend (React/Vite)       │
                │   live transcripts · approval queue · trace │
                │                  port 5173                  │
                └────────────────┬────────────────────────────┘
                                 │ HTTPS + WebSocket
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│                Transport Edge (Node / TS)                   │
│                       port 8080                             │
│                                                             │
│   ┌──────────────────┐   ┌────────────────────┐             │
│   │  WebRTC Signal   │   │  Twilio Media      │             │
│   │  (browser via    │   │  Streams (phone)   │             │
│   │  WebSocket+PCM)  │   │                    │             │
│   └─────────┬────────┘   └─────────┬──────────┘             │
│             └──────────┬───────────┘                        │
│                        ▼                                    │
│              Audio Gateway / Session Manager                │
│              (per-conversation OpenAI Realtime WS)          │
└──────────────────────┬──────────────────────────────────────┘
                       │  HTTP (sync tool calls, approvals)
                       │  WebSocket (push events)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                Agent Core (Python / FastAPI)                │
│                       port 8000                             │
│                                                             │
│   ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│   │  Tool       │  │  Guardrail / │  │  Approval state   │  │
│   │  Dispatcher │──│  Middleware  │──│  machine          │  │
│   └──────┬──────┘  └──────┬───────┘  └─────────┬─────────┘  │
│          │                │                    │            │
│          ▼                ▼                    ▼            │
│   ┌───────────────────────────────────────────────────────┐ │
│   │  Vertical Pack Loader                                 │ │
│   │  (HVAC pack, others later)                            │ │
│   │  tools.py · prompt.md · policy.yaml · approvals.yaml  │ │
│   └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
            ┌────────────────────────────────────┐
            │   Postgres        Redis            │
            │   (durable)       (pub/sub +       │
            │                    ephemeral)      │
            │   ports 5432, 6379                 │
            └────────────────────────────────────┘
```

Five containers; three load-bearing concerns.

---

## The three load-bearing things

The architecture is dominated by three concerns that are *shared* across
every surface and every vertical:

### 1. One agent core

The same planner, tools, prompts, and policies serve every surface
(browser, phone) and every vertical (HVAC today; real-estate /
founder-ops / telehealth in the design).

**Why this matters:** when you write a `parts_lookup` tool once, it
works identically on the phone, in the cockpit, in a future meeting
bot, with the right vertical pack loaded. There are no
per-surface tool implementations.

### 2. One conversation store

Every turn from every surface lands in the same Postgres tables,
keyed by conversation ID. Sessions can hand off between phone and
browser without losing context, because the context is in
Postgres — not in OpenAI's session memory.

**Why this matters:** durability + queryability + auditability.
Replay, eval scenarios, compliance — all enabled by this
choice.

### 3. One observability + guardrail spine

Every turn, regardless of transport, flows through the same trace
pipeline and the same guardrail/approval middleware. There is no
"trusted client" that bypasses guardrails. There is no "developer
mode" flag. The middleware is *inside* the dispatcher, not bolted
around it.

**Why this matters:** safety can't be subtly wrong. Either every tool
call goes through the gate, or you've broken the contract.

---

## Why hybrid Python + Node

The two services are written in different languages because they
have different jobs:

```
EDGE                                      CORE
────                                      ────
TypeScript on Node 20                     Python 3.11
Latency-critical                          Iteration-critical
Audio plane                               Brain
WebRTC, Twilio, OpenAI WS                 Tools, guardrails, persistence
~1500 lines of code                       ~3000 lines of code
Stateless per-conversation                Per-session runtime + Postgres
```

The seam between them is small and explicit:

| Direction | Protocol | What flows |
|---|---|---|
| Edge → Core (sync) | HTTP/JSON | `POST /v1/sessions`, `POST /v1/sessions/{id}/tool-calls`, `POST /v1/sessions/{id}/end` |
| Core → Edge (async) | WebSocket | `approval.resolved`, `mode.switch`, `speak.text` |

That's it. No shared memory. No language interop libraries. No RPC
generator. No version-pinned schema definitions to keep in sync. The
contract fits in a single page.

---

## The directory layout

```
gpt-realtime-2_openai/
│
├── core/                           ← Python agent core
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/
│   ├── src/cockpit_core/
│   │   ├── api/                    ← FastAPI routes
│   │   │   ├── health.py
│   │   │   ├── sessions.py
│   │   │   ├── conversations.py
│   │   │   ├── approvals.py
│   │   │   ├── verticals.py         ← business-status (Phase 4)
│   │   │   └── audits.py            ← divergence reads (Phase 5)
│   │   ├── agent/
│   │   │   ├── contract.py         ← Tool, Agent, ToolCallRequest, ...
│   │   │   ├── registry.py
│   │   │   ├── dispatch.py         ← the central loop
│   │   │   ├── approvals.py        ← state machine
│   │   │   ├── runtime.py          ← per-session runtime
│   │   │   └── lifecycle.py
│   │   ├── guardrails/
│   │   │   ├── middleware.py
│   │   │   └── pii.py
│   │   ├── store/                  ← asyncpg + raw SQL
│   │   │   ├── conversations.py
│   │   │   ├── turns.py
│   │   │   ├── tool_calls.py
│   │   │   ├── approvals.py
│   │   │   ├── trace_events.py
│   │   │   └── audit_divergences.py ← Phase 5
│   │   ├── observability/
│   │   │   ├── tracer.py
│   │   │   ├── sinks.py
│   │   │   ├── notifier.py
│   │   │   └── audit.py             ← divergence diff (Phase 5)
│   │   ├── verticals/
│   │   │   ├── loader.py
│   │   │   └── business_hours.py    ← Phase 4 predicate
│   │   ├── eval/
│   │   │   ├── runner.py
│   │   │   ├── cli.py
│   │   │   └── synthesize.py        ← Phase 6
│   │   ├── settings.py
│   │   ├── logging.py
│   │   ├── db.py
│   │   ├── redis_client.py
│   │   └── main.py
│   └── tests/
│
├── edge/                           ← Node transport edge
│   ├── package.json
│   ├── tsconfig.json
│   ├── src/
│   │   ├── server.ts
│   │   ├── settings.ts
│   │   ├── logging.ts
│   │   ├── health.ts
│   │   ├── core-client/index.ts
│   │   ├── webrtc/
│   │   │   ├── signaling.ts        ← browser audio bridge
│   │   │   └── peer.ts             ← future WebRTC peer-connection
│   │   ├── twilio/
│   │   │   ├── webhook.ts          ← /twilio/voice
│   │   │   ├── media-stream.ts     ← /twilio/media-stream
│   │   │   ├── routing.ts          ← TwiML builder
│   │   │   └── audio.ts            ← μ-law codec, resampler
│   │   ├── openai/
│   │   │   ├── session.ts          ← per-conversation Realtime WS
│   │   │   ├── transcription.ts    ← whisper WS (Phases 1–5)
│   │   │   ├── events.ts
│   │   │   └── sessions-registry.ts
│   │   └── voice-intent/
│   │       ├── classifier.ts       ← approval phrase matcher
│   │       └── lang-id.ts          ← language detection
│   └── tests/                       ← incl. transcription, sidecar, voicemail-routing
│
├── frontend/                       ← React cockpit
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── auth/
│       │   └── AuthGate.tsx
│       ├── cockpit/
│       │   ├── TalkPage.tsx        ← live audio + transcript
│       │   ├── TranscriptView.tsx
│       │   ├── ModeBadge.tsx
│       │   └── ModeToggle.tsx
│       ├── approvals/
│       │   └── ApprovalQueuePage.tsx
│       ├── voicemails/
│       │   └── VoicemailListPage.tsx       ← Phase 4
│       ├── audit/
│       │   └── AuditListPage.tsx           ← Phase 5
│       ├── conversations/
│       │   ├── ConversationListPage.tsx
│       │   └── TraceExplorerPage.tsx
│       └── lib/api.ts
│
├── verticals/
│   └── hvac/                       ← v1 vertical pack
│       ├── pack.yaml                ← incl. business_hours, audit_transcripts (Phase 4/5)
│       ├── prompt.md
│       ├── tools.py
│       ├── policy.yaml
│       ├── approvals.yaml
│       ├── preambles.yaml
│       ├── voicemail.md             ← greeting (Phase 4)
│       ├── post_call.py             ← per-mode summary shapes
│       ├── sandbox.py
│       ├── fixtures/
│       │   ├── parts.json
│       │   ├── trucks.json
│       │   ├── customers.json
│       │   ├── warranties.json
│       │   └── jobs.json
│       └── scenarios/
│           ├── 01_parts_lookup.yaml
│           ├── 02_schedule_move_approved.yaml
│           ├── 03_schedule_move_denied.yaml
│           ├── 04_spanish_translate_flip.yaml
│           ├── 05_multi_tool_parallel.yaml
│           ├── 06_translate_bilingual.yaml      ← Phase 2
│           ├── 07_notetaker_session.yaml        ← Phase 3
│           └── 08_voicemail_after_hours.yaml    ← Phase 4
│
├── infra/
│   └── postgres/init.sql
│
├── scripts/
│   ├── dev.sh
│   ├── seed-hvac.sh
│   ├── tunnel.sh
│   ├── replay-conversation.py
│   ├── trace-dump.py
│   ├── audit-divergences.py        ← Phase 5 nightly runner
│   └── synthesize-eval.py          ← Phase 6 eval generator
│
├── e2e/
│   └── run.sh
│
├── docs/                           ← this folder
│   ├── ops.md
│   ├── eval-format.md
│   ├── index.md
│   ├── overview/
│   ├── concepts/
│   ├── reference/
│   └── architecture/
│
├── .github/workflows/
│   ├── ci.yml
│   └── nightly.yml
│
├── docker-compose.yml
├── Makefile
├── README.md
├── SPEC.md
├── PLAN.md
├── CLAUDE.md
└── .env.example
```

---

## Data flow for one phone call (full detail)

```
PHONE                  TWILIO                 EDGE                  OPENAI                 CORE                  POSTGRES        REDIS
─────                  ──────                 ────                  ──────                 ────                  ────────        ─────

dial in ──────► PSTN routes ─►
                /twilio/voice
                webhook fires ─────────► validate signature
                                         lookup vertical
                                         ◄──────── return TwiML
                                         <Connect><Stream/>

                Twilio reads TwiML,
                opens Media Stream WS ─► /twilio/media-stream
                                         start event
                                         ─► POST /v1/sessions ──────────────────────────► create_conversation
                                                                                          load vertical pack         INSERT app.conversations
                                                                                          register runtime
                                         ◄──── session config ──────────────────────────
                                         open OpenAI WS ─────────────►
                                                                       authenticated
                                                                       session.created
                                         ─── session.update ──────────►

                send μ-law frames ─────► decode μ-law
                                         resample 8→24
                                         ─── input_audio_buffer.append ──►
                                         ...                            ...
                                                                       VAD: speech_stopped
                                                                       run model
                                                                       ◄── response.done
                                                                            with function_call

                                         POST /v1/sessions/{id}/tool-calls ──────────────►
                                                                                          dispatcher.execute()
                                                                                          - guardrail before_tool_call
                                                                                          - blast_radius == "dangerous"?
                                                                                            yes → create approval         INSERT app.approvals  publish 'approval.requested'
                                                                                            wait                                                  (cockpit shows badge)
                                                                                          - on resolution:
                                                                                            run handler
                                                                                            update tool_call               UPDATE app.tool_calls publish 'approval.resolved'
                                         ◄──── ToolCallResult ─────────────────────────────
                                         ─── conversation.item.create ──►
                                              type: function_call_output
                                         ─── response.create ──►
                                                                       generate response
                                                                       ◄── output_audio.delta * N ──
                                         resample 24→8
                                         encode μ-law
                ◄── media events ───────
play to caller

                ...turn loop continues...

caller hangs up ─► Twilio stop ─► /twilio/media-stream
                                  stop event
                                  close OpenAI WS
                                  POST /v1/sessions/{id}/end ──────────────────────────► finish_session
                                                                                          fire post_call hook            UPDATE app.conversations
                                                                                                                          (ended_at)
```

---

## Key decisions, with rationale

These are the choices that most affect how the system feels.

### Decision: Conversation state in Postgres, not in OpenAI's session

**Why.** OpenAI's session memory disappears when the WebSocket
closes. Building anything durable on top of it (replay, eval,
audit) requires a parallel store. Skipping the parallel store and
just using OpenAI is a road that ends in pain.

**Trade-off.** Slightly more work per turn (we write to Postgres
on every transcript and tool call). Worth it.

### Decision: Edge owns audio, core owns logic

**Why.** Audio is latency-critical and well-served by Node's event
loop and WebSocket libraries. Logic is iteration-heavy and
well-served by Python's tooling. Splitting them on this boundary
plays to each language's strengths.

**Trade-off.** Two languages to maintain. Mitigated by a tight, simple
seam (HTTP+WS).

### Decision: Tools live in vertical packs, not in the platform

**Why.** Verticals come and go independently. A real-estate operator
shouldn't have to fork the platform to ship their CRM tool.

**Trade-off.** Some boilerplate in each pack. Mitigated by a
strict, minimal `Tool` contract.

### Decision: Guardrails inside the dispatcher, not around it

**Why.** Bolting guardrails on the outside means there's a path
through the dispatcher that bypasses them. Putting them *inside*
means there's literally no other path.

**Trade-off.** Less flexibility for "fast paths." We don't want fast
paths.

### Decision: Approvals block the agent loop

**Why.** A spoken "Reggie, do it" should resume the conversation
naturally. If the agent loop didn't block, the model would have
already moved on by the time the approval landed.

**Trade-off.** A hung approval blocks one conversation for up to 60
seconds. The 60s timeout caps that, and the model can recover
with a graceful denial response.

### Decision: WebSocket+PCM for browser, not full WebRTC, in v1

**Why.** Less code, no signaling state machine, works through
corporate firewalls. The latency penalty on a local network is
negligible; on a lossy network it's real.

**Trade-off.** Worse on packet loss. The seam to add real WebRTC
later is reserved.

### Decision: μ-law ↔ PCM linear-interpolation resample

**Why.** Phone audio is band-limited to 3.4 kHz at the carrier;
linear interpolation is indistinguishable from a polyphase filter
for speech. ~30 lines of TypeScript vs. a DSP library.

**Trade-off.** Won't sound good on music or wide-band sources. We
don't have those.

### Decision: Single-replica core, single-replica edge

**Why.** v1 is single-tenant self-host. Operators run it on one VM.
HA is out of scope.

**Trade-off.** Restarting the core mid-call drops in-flight
approvals. The seam to externalize the approval waiter map (via
Redis) is small.

---

## What's intentionally simple about this system

- **No service mesh.** Two services on a docker-compose network
  reach each other by hostname. No Istio, no Linkerd, no mTLS
  inside the cluster.
- **No message queue.** Redis pub/sub handles the one cross-service
  push channel we need. No RabbitMQ, no Kafka, no SQS.
- **No GraphQL gateway.** The cockpit talks to the core via REST.
  Five endpoints. No federation.
- **No ORM in the runtime.** Hand-written async SQL via asyncpg.
- **No multi-region.** One VM. One Twilio media-stream pop. One
  OpenAI region (your choice via API).

Each of these is a deliberate "no" in the spec. They're not
absent because we forgot — they're absent because v1 doesn't earn
them. The seams to add any of them are clean.

---

## What's deliberately complex (but worth it)

- **The approval state machine.** Looks simple (4 states), but the
  voice + cockpit race conditions, the timeout, and the per-conversation
  pending stack all add up. The complexity is intrinsic to the
  problem.
- **The trace pipeline.** Async-batched writes, queue with
  drop-with-counter, two sinks (Postgres + stdout) — more than the
  naïve "write each event directly." Justified by the latency
  budget.
- **The vertical pack loader.** Reflective import of `tools.py`
  with a synthetic parent package, schema-driven YAML validation,
  pluggable post_call hooks. Justified by the platform thesis: new
  verticals must be small to ship.

---

## Ports / paths summary

| Port | Service | Public? | Purpose |
|---|---|---|---|
| 5173 | frontend | dev only | Vite dev server |
| 8000 | core | internal | FastAPI agent core |
| 8080 | edge | public | HTTP webhooks + WebSockets |
| 5432 | postgres | internal | Database |
| 6379 | redis | internal | Pub/sub |

Public-facing routes on port 8080:

| Path | Method | Purpose |
|---|---|---|
| `/healthz` | GET | Health check |
| `/twilio/voice` | POST | Twilio voice webhook |
| `/twilio/media-stream` | WS | Twilio Media Stream |
| `/v1/voice/browser` | WS | Browser audio bridge |

Internal routes on port 8000:

| Path | Method | Purpose |
|---|---|---|
| `/healthz` | GET | Health check |
| `/v1/sessions` | POST | Create a session |
| `/v1/sessions/{id}/tool-calls` | POST | Execute a tool |
| `/v1/sessions/{id}/end` | POST | End a session |
| `/v1/sessions/{id}/mode` | POST | Switch mode |
| `/v1/sessions/{id}/transcript` | POST | Push transcript chunks |
| `/v1/sessions/{id}/approval-by-voice` | POST | Resolve approval by spoken phrase |
| `/v1/sessions/{id}/events` | WS | Per-session push channel |
| `/v1/conversations` | GET | List conversations (filterable by `?mode=...`) |
| `/v1/conversations/{id}` | GET | Conversation detail |
| `/v1/conversations/{id}/turns` | GET | Turn list (includes `model` per turn) |
| `/v1/conversations/{id}/tool-calls` | GET | Tool call list |
| `/v1/conversations/{id}/trace` | GET | Trace event list |
| `/v1/approvals` | GET | List pending approvals |
| `/v1/approvals/{id}/resolve` | POST | Resolve approval (cockpit click) |
| `/v1/verticals/{name}/business-status` | GET | Whether the vertical is open + voicemail greeting (Phase 4) |
| `/v1/audits/divergences` | GET | Audit divergence rows (Phase 5) |

---

## Where to read next

- The spec: [SPEC.md](../../SPEC.md).
- The plan: [PLAN.md](../../PLAN.md).
- Operations: [docs/ops.md](../ops.md).
