# Voice Operations Cockpit — Platform Spec

**Version:** 0.1 (v1 scope)
**Status:** Draft, awaiting confirmation
**Last updated:** 2026-05-07

---

## 1. Objective

Build a unified, self-hostable **voice operations cockpit** on top of OpenAI's
GPT-Realtime API family. One agent core, multiple surfaces (browser + phone),
multiple modes (conversational + translation), one observability/guardrail
spine. Verticals (HVAC dispatcher, real-estate, founder ops, telehealth) are
*configurations* on the platform, not separate apps.

### Problem

Voice agents today are usually built as single-surface point solutions:
a phone bot, a browser chat, a meeting assistant. Each one has its own
tools, prompts, memory, and observability — which means the human ends
up being the integration layer. The cockpit collapses these into one
agent brain that shows up wherever the user is, with shared memory and
shared safety rails.

### Target users (v1)

A small operator (1–10 people) who needs:

- Inbound phone handling that does real work (lookups, scheduling, CRM updates).
- A browser cockpit for staff to give voice commands and observe live calls.
- Strong guardrails and approval gates on consequential actions.
- Full traceability of every turn, tool call, cost, and decision.

**v1 ships with the HVAC dispatcher vertical** as the first vertical riding
on the platform. Real-estate, founder-ops, and telehealth verticals are
described in this spec as design pressure — they are *not* built in v1.

### Success criteria

A v1 release is successful when all of the following are true:

1. A real Twilio phone number, dialled from outside, is answered by the agent
   over the WebSocket bridge with end-to-end latency under 1.5 s for the
   first audible response.
2. A staff user opens the browser cockpit, presses talk, and gives a voice
   command that executes a tool with the same agent identity and shared
   conversation memory.
3. A "dangerous" tool call (per `approvals.yaml`) is held pending and
   resolves only after explicit approval (spoken phrase or cockpit click).
4. Every turn, tool call, guardrail decision, and approval is persisted
   and visible in the cockpit's trace view.
5. `docker compose up` from a fresh clone, plus a `.env` file with API
   keys, brings up the full stack (Postgres, Redis, Python core, Node
   edge, frontend) and the system answers a test call.

---

## 2. Architecture Overview

### Three load-bearing shared things

The platform is one project, not three glued together, because these
three concerns are shared across every surface and every vertical:

1. **One agent core** — the same planner, tools, prompts, and policies
   serve every surface (browser, phone) and every vertical.
2. **One conversation store** — every turn from every surface lands in
   the same store, keyed by conversation id; sessions can hand off
   between phone and browser without losing context.
3. **One observability + guardrails spine** — every turn, regardless of
   transport, flows through the same trace pipeline and the same
   guardrail/approval middleware.

### High-level component diagram

```
                  ┌──────────────────────────────────────────────────┐
                  │           Cockpit Frontend (React/Vite)          │
                  │    live transcripts · approval queue · traces    │
                  └────────────────┬─────────────────────────────────┘
                                   │ HTTPS + WebSocket
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Transport Edge (Node / TS)                     │
│                                                                     │
│   ┌──────────────────┐   ┌────────────────────┐   ┌─────────────┐   │
│   │  WebRTC Signal   │   │  Twilio Media      │   │  OpenAI     │   │
│   │  (browser)       │   │  Streams (phone)   │   │  Realtime   │   │
│   └─────────┬────────┘   └─────────┬──────────┘   │  Sessions   │   │
│             └──────────┬───────────┘              └──────┬──────┘   │
│                        ▼                                 │          │
│              Audio Gateway / Session Manager  ◄──────────┘          │
│         (per-conversation OpenAI Realtime WS sockets)               │
└─────────────────────┬───────────────────────────────────────────────┘
                      │  HTTP (sync tool calls, approvals)
                      │  WebSocket (push events)
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Agent Core (Python / FastAPI)                 │
│                                                                     │
│   ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
│   │  Planner +  │  │  Tool        │  │  Guardrail / Approval    │   │
│   │  Workers    │──│  Registry    │──│  Middleware              │   │
│   └─────────────┘  └──────┬───────┘  └────────────┬─────────────┘   │
│                           ▼                       ▼                 │
│                   ┌───────────────────────────────────┐             │
│                   │  Vertical Pack (HVAC, RE, …)      │             │
│                   │  tools.py · prompt.md             │             │
│                   │  policy.yaml · approvals.yaml     │             │
│                   └─────────────┬─────────────────────┘             │
└─────────────────────────────────┼───────────────────────────────────┘
                                  ▼
                ┌────────────────────────────────────┐
                │   Postgres   ·   Redis             │
                │   (conv, turns, traces, approvals) │
                │   (sessions, pub/sub, queues)      │
                └────────────────────────────────────┘
```

### Why hybrid Python + Node

- **Node owns the audio plane.** WebRTC signaling, Twilio Media Streams
  (μ-law over WebSocket), and the persistent WebSocket session to
  OpenAI Realtime all live on the latency-critical edge. Node's
  ecosystem here is the most mature.
- **Python owns the brain.** Tool implementations, agent orchestration,
  guardrails, persistence, observability, and all vertical packs live
  in Python. This is where the iteration happens and where most
  developers will work.
- **The seam is small and explicit.** Node calls Python over HTTP for
  synchronous tool executions; Python pushes events to Node over a
  per-session WebSocket. No shared memory, no language interop libs.

### Surfaces

| Surface         | Transport            | Mode default     | Direction |
|-----------------|----------------------|------------------|-----------|
| Browser cockpit | WebRTC               | Realtime-2       | Bidirectional |
| Phone (inbound) | Twilio Media Streams | Realtime-2       | Bidirectional |
| Phone (outbound)| Twilio Media Streams | Realtime-2       | Bidirectional, v1.1 |
| Translate mode  | Either transport     | Realtime-Translate | Mode toggle per session |

### Modes

The four supported session modes (post-Phase-1 widening):

- **`realtime2`** — the conversational default, powered by
  `gpt-realtime-2`. Reasoning, tool calls, preambles, parallel
  actions.
- **`translate`** — mode toggle on an active session, powered by
  `gpt-realtime-translate`. Passthrough translation; tools and
  orchestration are bypassed.
- **`voicemail`** — start-time-only mode for inbound calls outside
  a vertical's `business_hours`. Powered by `gpt-realtime-whisper`
  in solo mode (no agent persona, no tools).
- **`notetaker`** — start-time-only mode for dispatcher-initiated
  silent transcription. Powered by `gpt-realtime-whisper` in solo
  mode.

Mid-session swaps are allowed only between `realtime2` and
`translate`. The other two are start-time only and are gated at the
`ModeSwitchBody.mode` Pydantic literal in `core/api/sessions.py`.

---

## 3. Components

### 3.1 Agent Core (Python)

- **Framework:** FastAPI for HTTP, `websockets` for outbound push.
- **Agent runtime:** thin in-house loop on top of the OpenAI Python SDK.
  Not LangChain. Not LangGraph. Direct, observable, debuggable.
- **Responsibilities:**
  - Maintains the tool registry per active conversation.
  - Receives tool-call requests from the transport edge, applies
    guardrails + approval policy, executes, returns result.
  - Owns the vertical pack lifecycle: load on session start, tear down
    on session end.
  - Emits trace events for every decision.
- **Does not:** hold open WebSocket sessions to OpenAI; touch raw audio.

### 3.2 Transport Edge (Node / TypeScript)

- **Framework:** Fastify + `ws`. No Express.
- **Responsibilities:**
  - Browser: WebRTC signaling (offer/answer/ICE) to negotiate the
    audio peer connection. Bridges browser audio to OpenAI Realtime.
  - Phone: receives Twilio Media Streams WebSocket, decodes μ-law,
    bridges to OpenAI Realtime, encodes back to μ-law.
  - Maintains one OpenAI Realtime WebSocket per active conversation.
  - When OpenAI emits a tool-call event, calls the Python core over
    HTTP and injects the result back into the OpenAI session.
  - Mirrors transcript deltas + state events to subscribed cockpit
    frontends over WebSocket.
- **Does not:** execute tools, decide approvals, write to Postgres.

### 3.3 Conversation Store (Postgres)

Single source of truth for all durable conversation data. See §5.

### 3.4 Ephemeral State (Redis)

- Active session registry (conversation_id → edge node, OpenAI session id).
- Approval pub/sub channel (frontends subscribe, backend publishes).
- Audio buffer ring for the most recent N seconds per session
  (for diagnostics / replay).
- Rate limiting tokens.

### 3.5 Observability + Guardrails Spine

A library imported by the agent core (and by tools). It is not a
separate service — it is a discipline enforced at the seams.

- **Trace pipeline:** structured event emitter that writes to Postgres
  `trace_events` and (optional) a configurable sink (OTLP, file, stdout).
- **Guardrails:**
  - Pre-call: input filtering (PII detection, profanity, off-policy intent).
  - Tool-call: classification by `blast_radius` and approval gating.
  - Post-call: output filtering (PII redaction in transcripts, refusal
    taxonomy enforcement).
- **Approvals:** every dangerous tool call creates an `ApprovalRequest`
  row, publishes to the Redis approvals channel, and either resolves
  via voice phrase (parsed by a lightweight intent classifier on the
  edge) or cockpit click. Default timeout: 60 s, configurable per tool.

### 3.6 Frontend Cockpit (React / Vite + Tailwind)

- Live conversation view: transcript, audio waveform, mode badge.
- Approval queue with one-click resolve.
- Trace explorer: waterfall of events per conversation, costs, tool
  calls, latencies.
- Tool registry browser: see what the active vertical exposes.
- Vertical switcher: pick which pack a session uses.
- Auth: single operator login (basic auth via env-set credentials in
  v1; OIDC is v2).

---

## 4. Verticals

A vertical is a package directory. Adding a vertical does not require
modifying the platform.

### 4.1 Vertical pack shape

```
verticals/<name>/
├── pack.yaml                # name, version, default mode, supported surfaces
├── prompt.md                # system prompt, persona, voice instructions
├── tools.py                 # tool implementations
├── policy.yaml              # guardrails: PII rules, refusal taxonomy, language
├── approvals.yaml           # which tools require approval, thresholds
├── preambles.yaml           # canonical preamble phrases per tool
└── post_call.py             # post-conversation hooks (file CRM, email, etc.)
```

### 4.2 HVAC dispatcher (v1 implementation)

- **Personas:** Aria the dispatcher.
- **Surfaces:** phone primary, browser for the human dispatcher.
- **Tools:**
  - `parts_lookup(model_number, part_description) -> PartInfo`
  - `truck_inventory(truck_id, part_number) -> InventoryRow`
  - `warranty_check(unit_serial) -> WarrantyStatus`
  - `schedule_lookup(date_range, tech_id?) -> Job[]`
  - `schedule_move(job_id, new_slot) -> SchedResult`  *(approval-gated)*
  - `dispatch_truck(job_id, truck_id) -> DispatchAck`  *(approval-gated)*
  - `customer_lookup(phone_or_address) -> Customer`
- **Approval rules:** any tool that mutates the schedule, dispatches a
  truck, or initiates a parts order requires approval (spoken "Reggie, do
  it" or cockpit click).
- **Translate trigger:** if the inbound caller's first 3-second
  language detection is not English, switch to Translate mode and
  surface English transcript to the dispatcher.

### 4.3 Real-estate brokerage (designed, not built in v1)

- **Personas:** Aria the broker assistant.
- **Surfaces:** phone primary, browser for the broker.
- **Tools:** MLS listing lookup, calendar (broker + co-broker + listing
  agent), CRM contact creation, showing scheduling.
- **Approval rules:** showings on listings above a configurable price
  threshold; any contact handoff to a co-broker.

### 4.4 Solo SaaS founder ops (designed, not built in v1)

- **Surfaces:** browser primary, phone for inbound demos.
- **Tools:** Sentry, GitHub Actions deploys, Datadog, Intercom, Slack,
  Calendly.
- **Approval rules:** any production deploy or refund. Voice phrase
  default: *"ship it, my responsibility"*.
- **Background tasks:** deploy + healthcheck loops run as long-running
  agent tasks; the agent narrates state without blocking the call.

### 4.5 Telehealth intake (designed, not built in v1)

- **Surfaces:** phone primary.
- **Tools:** EHR appointment lookup/book, insurance verification,
  voicemail triage.
- **Approval rules:** strict — every EHR write held pending; PHI redaction
  in transcripts before storage.
- **Safety:** medical-symptom classifier; any positive trigger forces a
  warm transfer to a human nurse line, no exceptions.
- **Compliance note:** v1 platform is **not** HIPAA-ready. This vertical
  exists to design-pressure the safety/compliance spine, not to ship.

---

## 5. Data Model

All tables in `app` schema; conversation_id is a UUIDv7 (sortable).

```
conversations (
  id              uuid          pk
  vertical        text          not null
  surface         text          not null  -- 'browser' | 'phone'
  mode            text          not null  -- 'realtime2' | 'translate'
                                           --   | 'voicemail' | 'notetaker'
                                           --   (CHECK widened by migration 0002)
  language        text          null      -- BCP-47, set after detect
  customer_ref    jsonb         null      -- vertical-defined
  agent_persona   text          null
  started_at      timestamptz   not null
  ended_at        timestamptz   null
  cost_usd        numeric(10,4) not null default 0
)

turns (
  id              uuid          pk
  conversation_id uuid          fk -> conversations.id
  role            text          not null  -- 'user' | 'agent' | 'tool' | 'system'
  transcript      text          null
  audio_uri       text          null      -- s3-style, optional
  model           text          null
  latency_ms      int           null
  ts              timestamptz   not null
)

tool_calls (
  id              uuid          pk
  conversation_id uuid          fk
  turn_id         uuid          fk
  tool_name       text          not null
  args_json       jsonb         not null
  result_json     jsonb         null
  status          text          not null  -- 'requested' | 'approved' | 'denied' | 'executed' | 'failed'
  blast_radius    text          not null  -- 'read' | 'safe-write' | 'dangerous'
  approval_id     uuid          null      -- fk -> approvals.id
  started_at      timestamptz   not null
  finished_at     timestamptz   null
)

approvals (
  id              uuid          pk
  conversation_id uuid          fk
  tool_call_id    uuid          fk
  requested_at    timestamptz   not null
  resolved_at     timestamptz   null
  decision        text          null      -- 'approved' | 'denied' | 'timeout'
  decided_by      text          null
  decided_via     text          null      -- 'voice' | 'cockpit' | 'auto'
  timeout_seconds int           not null default 60
)

trace_events (
  id              uuid          pk
  conversation_id uuid          fk
  ts              timestamptz   not null
  kind            text          not null  -- 'turn.start' | 'tool.requested' | 'guardrail.fired' | …
  payload_json    jsonb         not null
  cost_usd        numeric(10,6) not null default 0
)

-- Added by migration 0003 (Phase 5 — audit transcripts).
-- Populated by the `make audit` runner for verticals with
-- `audit_transcripts: true`.
audit_divergences (
  id                 uuid          pk
  conversation_id    uuid          fk
  agent_turn_id      uuid          null    -- nullable when the agent missed an utterance
  canonical_turn_id  uuid          null    -- nullable when the agent imagined an utterance
  kind               text          not null -- 'paraphrase' | 'omission' | 'addition' | 'mismatch'
  score              numeric(5,4)  not null -- token-level WER, normalized
  agent_text         text          null
  canonical_text     text          null
  flagged_at         timestamptz   not null default now()
)
```

Migrations via `alembic`. No ORM — raw SQL via `asyncpg` for the agent
core. Good fit for the volume; ORM cost is not earned here.

---

## 6. Interfaces & Contracts

### 6.1 Agent contract (Python)

```python
class Agent(Protocol):
    vertical: str
    persona: str
    tools: list[Tool]
    guardrails: list[Guardrail]

    async def on_session_start(self, ctx: SessionContext) -> None: ...
    async def on_session_end(self, ctx: SessionContext) -> None: ...
    async def on_tool_call(self, req: ToolCallRequest) -> ToolCallResult: ...
```

### 6.2 Tool contract

```python
@dataclass
class Tool:
    name: str
    description: str
    schema: dict           # JSON schema for args
    blast_radius: Literal["read", "safe-write", "dangerous"]
    handler: Callable[[ToolCallRequest], Awaitable[Any]]
    preamble: str | None   # what to say before invoking
```

### 6.3 Edge ↔ Core protocol

**Sync, edge → core (HTTP):**

- `POST /v1/sessions`  — create a conversation, returns id + initial config.
- `POST /v1/sessions/{id}/tool-calls`  — request execution, returns result
  or pending-approval marker.
- `POST /v1/sessions/{id}/end`  — finalize.

**Async, core → edge (per-session WebSocket):**

- `event: approval.resolved` — a held tool call may now proceed.
- `event: mode.switch` — change session mode (realtime2 ↔ translate).
- `event: speak.text` — instruct the edge to inject text into the
  OpenAI Realtime session (used for preambles + post-approval
  status updates).

### 6.4 Trace event schema

```json
{
  "ts": "2026-05-07T12:00:00Z",
  "conversation_id": "uuid",
  "kind": "tool.requested",
  "actor": "agent",
  "payload": { "tool": "schedule_move", "args": { … } },
  "cost_usd": 0.0,
  "vertical": "hvac",
  "surface": "phone"
}
```

All trace writes are async-batched. Backpressure: drop with a logged
counter rather than block the agent loop. We can replay from
`turns` + `tool_calls` if traces are lost.

---

## 7. Project Structure

```
gpt-realtime-2_openai/
├── SPEC.md                            ← this document
├── README.md
├── docker-compose.yml
├── .env.example
├── docs/                              ← existing reference material
│
├── core/                              ← Python agent core
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── src/cockpit_core/
│   │   ├── api/                       ← FastAPI routes
│   │   ├── agent/                     ← runtime, planner, tool dispatch
│   │   ├── guardrails/
│   │   ├── store/                     ← asyncpg + queries
│   │   ├── observability/             ← tracer, sinks
│   │   ├── verticals/                 ← pack loader
│   │   └── main.py
│   └── tests/
│
├── edge/                              ← Node transport edge
│   ├── package.json
│   ├── tsconfig.json
│   ├── src/
│   │   ├── server.ts
│   │   ├── webrtc/                    ← signaling
│   │   ├── twilio/                    ← media-streams handler
│   │   ├── openai/                    ← Realtime session manager
│   │   ├── core-client/               ← HTTP + WS to Python core
│   │   └── voice-intent/              ← lightweight phrase classifier
│   └── tests/
│
├── frontend/                          ← React cockpit
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│
├── verticals/
│   └── hvac/
│       ├── pack.yaml
│       ├── prompt.md
│       ├── tools.py
│       ├── policy.yaml
│       ├── approvals.yaml
│       ├── preambles.yaml
│       └── post_call.py
│
├── infra/
│   ├── postgres/                      ← init.sql + migrations
│   ├── redis/
│   └── nginx/                         ← optional reverse proxy for self-host
│
└── scripts/
    ├── dev.sh
    ├── seed-hvac.sh
    └── replay-conversation.py         ← debug tool
```

---

## 8. Commands

All commands assume Docker and a working `.env` file copied from
`.env.example`. Required env vars:

- `OPENAI_API_KEY`
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`
- `COCKPIT_OPERATOR_USER`, `COCKPIT_OPERATOR_PASSWORD`
- `POSTGRES_PASSWORD`
- `PUBLIC_BASE_URL` (for Twilio webhooks)

### Dev

```
make dev              # docker compose up with hot-reload mounts
make migrate          # alembic upgrade head
make seed             # load HVAC fixtures: parts catalog, sample customers
make tunnel           # cloudflared tunnel for Twilio inbound webhooks
```

### Test

```
make test             # full suite (unit + integration + e2e against mocks)
make test-core        # Python only
make test-edge        # Node only
make test-eval        # vertical scenario evals (recorded replays)
```

### Deploy (single-tenant self-host)

```
make build            # build images
make up               # docker compose up -d
make logs
make down
```

### Operator

```
make replay CONV=<uuid>   # recreate a past conversation in dev for debugging
make trace CONV=<uuid>    # dump trace timeline as text
```

---

## 9. Code Style

### Python (core, verticals)

- Formatter: `black` + `ruff` (line length 100).
- Types: `mypy --strict`. No untyped public functions.
- Async-first; never block the event loop. Use `asyncpg` not psycopg.
- No global state. Pass `SessionContext` explicitly.
- Public functions: one-line docstring describing intent. No multi-paragraph
  docstrings unless documenting a non-obvious invariant.

### TypeScript (edge, frontend)

- `prettier` + `eslint`, `tsconfig` strict.
- No `any` outside the OpenAI Realtime SDK boundary; cast at the seam.
- Functions returning Promises must be awaited or explicitly fired-and-logged.
- Frontend: function components only; React hooks; Tailwind for styling;
  no UI library beyond shadcn primitives.

### Logging

- Structured logs everywhere (JSON). Field names: `conversation_id`,
  `surface`, `vertical`, `tool`, `level`, `msg`, `ts`.
- No PII in logs. PII redaction is applied at the trace boundary.

### Comments

- Default: no comments. Code is the documentation.
- Exception: hidden constraints, OpenAI API quirks, regulatory or
  audio-format invariants. Always say *why*.

---

## 10. Testing Strategy

A test is worth writing only if it would catch a real regression. The
test pyramid here is wide on unit, narrow on e2e, with a vertical
scenario eval suite that is the most load-bearing safety net.

### 10.1 Unit (Python core)

- Tool handlers: pure-function tests with stubbed external integrations.
- Guardrails: positive + negative cases per rule.
- Approval state machine: every legal transition + every illegal one.
- Trace serialization: schema round-trip.

### 10.2 Unit (Node edge)

- μ-law ↔ PCM conversion fixtures.
- WebRTC signaling state machine.
- Voice-intent classifier: gold set per approval phrase.

### 10.3 Contract tests

A small fixture suite that exercises the edge ↔ core HTTP and
WebSocket protocol with mocks on both sides. If the protocol changes,
these tests fail loudly.

### 10.4 Integration

- Postgres-backed store tests: real Postgres in a Docker test
  container, no mocks for the persistence layer.
- Mocked OpenAI Realtime: a recorded fixture player that emits the
  same WebSocket events OpenAI does. Integration tests run the agent
  loop end-to-end against this player.

### 10.5 End-to-end smoke

`make test-e2e`: brings up the full docker-compose stack, dials the
mocked Twilio bridge, plays a canned audio file, and asserts the
expected tool calls + approvals fired in the correct order.

### 10.6 Vertical scenario evals

For each vertical pack: a YAML-defined scenario file describes
`(transcript_in, expected_tools_called, expected_approvals,
expected_transcript_out_contains)`. The eval harness replays each
scenario and scores. A scenario regression blocks merge.

HVAC v1 must include at least:

- Parts lookup (read, no approval).
- Schedule move (dangerous, approval required, approval granted by voice).
- Schedule move with denial.
- Spanish-speaking inbound caller → translate-mode flip.
- Multi-tool turn: parts lookup + warranty check + schedule view in one
  agent reply, with parallel tool calls.

---

## 11. Boundaries

### Always

- Every tool call passes through the guardrail middleware before
  execution. No exceptions, no "trusted" tools.
- Every dangerous tool call creates an approval row before execution
  and waits for resolution.
- Every turn, tool call, and guardrail decision emits a trace event.
- Every persisted transcript passes through PII redaction.
- Every prompt template is version-pinned per vertical. Prompts are
  data, not code.
- Migrations are forward-only; rollback is via re-migration, not
  destructive `down` steps.

### Ask first

- Adding a new tool with `blast_radius: dangerous`.
- Lowering a default approval threshold.
- Removing or weakening a guardrail rule.
- Schema migrations that change column semantics on existing tables.
- Switching the OpenAI Realtime model or voice mid-session.
- Anything that touches PII storage policy.

### Never

- Bypass the guardrail layer with a "developer mode" flag.
- Log raw audio without an explicit consent flag on the conversation.
- Write to production tools (real CRMs, real schedulers) from a dev
  environment. Use vertical-pack-defined sandbox endpoints.
- Pin secrets into the agent prompt. All secrets live in env-injected
  config, never in `prompt.md`.
- Auto-approve a held tool call based on heuristic intent — only an
  explicit voice phrase or cockpit click resolves an approval.
- Use any LLM other than OpenAI Realtime for the conversational loop in
  v1. Out-of-band classifiers (PII, intent) may use small local models.

---

## 12. Out of Scope for v1

These are deliberately deferred. The platform's seams are designed so
each one is additive:

- Outbound calling (agent dials out).
- Multi-tenant SaaS (auth, RLS, per-tenant config, billing).
- Meeting overlay (Zoom/Meet bot) — Translate mode is reachable from
  browser/phone in v1; the meeting bot is a v1.1 transport.
- Verticals beyond HVAC (real-estate, founder-ops, telehealth are
  designed in this spec but not implemented).
- HIPAA / SOC 2 readiness work for the telehealth vertical.
- OIDC / SSO; v1 is single-operator basic auth.
- Replay-from-production-to-staging tooling beyond the dev-only
  `replay-conversation.py` script.
- Multi-region / HA deploys.

---

## 13. Resolved Design Decisions

Locked-in choices made during spec review. These are part of the
contract; revisiting them requires updating this section.

1. **Voice-intent classifier:** **local**. A small speech recognizer +
   per-tool trigger phrases runs in the Node edge. The classifier sits
   behind a clean interface so an OpenAI round-trip variant can be
   added later without touching callers.
2. **Audio storage:** **none in v1**. Only transcripts are persisted.
   The store schema reserves `turns.audio_uri` so an S3-compatible
   backend can be added when a vertical (e.g. telehealth) requires it.
3. **Approval-on-voice phrase parsing:** **exact phrase per tool**.
   Each tool in `approvals.yaml` declares its own approval phrase. No
   fuzzy intent matching in v1 — false approvals are unacceptable on
   dangerous actions.
4. **Frontend hosting:** **separate container**. The cockpit UI ships
   as its own service (nginx serving built Vite assets) so frontend
   asset traffic does not compete with the audio edge.
5. **Whisper endpoint** *(Phase 1+ addendum)*: streaming transcription
   uses OpenAI's dedicated `wss://api.openai.com/v1/realtime?intent=transcription`
   URL, not the conversational `?model=` URL family. Model id flows
   in the session.update payload at
   `audio.input.transcription.model`. The cockpit's
   `TranscriptionSession` class encapsulates this; the URL is
   contract-pinned in `edge/tests/transcription.test.ts`.
6. **Mode mid-session switching** *(Phase 3+ addendum)*: only
   `realtime2 ↔ translate` flips are permitted at runtime. `voicemail`
   and `notetaker` are start-time-only modes (gate enforced by the
   `ModeSwitchBody.mode` Pydantic literal).
7. **Audit transcripts opt-in** *(Phase 5+ addendum)*: per-vertical
   `audit_transcripts: true` flag in `pack.yaml`. When set, a
   `gpt-realtime-whisper` sidecar runs always-on alongside the
   primary session, enabling the divergence-diff pipeline. Default
   off; HVAC stays off.
8. **Eval generation source** *(Phase 6+ addendum)*: v1 reads
   transcripts from `app.turns` (no live whisper, no audio replay),
   honoring §13.2's no-audio-storage decision. v1.5 may accept a
   stored audio file and re-transcribe with whisper.

---

## 14. Build Order (informational, not part of the contract)

The spec is the contract; build order is a planning concern. Suggested
first vertical slice for incremental implementation:

1. Postgres + migrations + minimal store API.
2. Python core skeleton: agent contract, tool registry, one trivial
   tool, trace pipeline.
3. Node edge skeleton: OpenAI Realtime session manager + a single
   browser WebRTC test page that round-trips audio.
4. End-to-end browser → core → tool → response over WebRTC.
5. Twilio Media Streams bridge; the same flow over phone.
6. Approval flow: introduce one dangerous tool, voice phrase resolver,
   cockpit approval click.
7. HVAC vertical pack: tools, prompt, policies, approvals, preambles.
8. Translate mode toggle.
9. Frontend cockpit: live transcript, approval queue, trace explorer.
10. Eval harness + HVAC scenario suite.

Each step should be shippable on its own; nothing here forces a big-bang.
