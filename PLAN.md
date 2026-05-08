# Implementation Plan: Voice Operations Cockpit

**Source spec:** `SPEC.md` v0.1
**Plan version:** 0.1
**Last updated:** 2026-05-07

---

## Overview

Build the Voice Operations Cockpit in nine phases, vertically sliced
so each phase ends with shippable, testable functionality. The first
five phases stand up the platform end-to-end on a single trivial tool.
Phase 6 lands the HVAC vertical. Phases 7–9 add Translate mode, the
eval harness, and ship polish.

The plan is ordered to **fail fast**: the riskiest integrations
(OpenAI Realtime, Twilio Media Streams, voice-intent classifier) are
exercised early on minimal scaffolding, before HVAC content is built
on top. If any of those don't work the way the spec assumes, we find
out before we've sunk effort into vertical content.

---

## Architecture Decisions Affecting the Plan

- **Hybrid Python + Node** means each phase usually has work in both
  trees. Where possible, tasks are split so Python and Node work can
  proceed in parallel within a phase (see "Parallelization" below).
- **Vertical slicing over horizontal slicing.** Phase 2 ships a
  minimum end-to-end voice loop with one trivial tool, before any
  persistence, approvals, or HVAC content lands.
- **Mocks at integration boundaries.** OpenAI Realtime and Twilio
  Media Streams have recorded-fixture replay players so the integration
  tests don't depend on live API access.
- **Foundations don't include guardrails.** The guardrail layer has
  hook points carved out from Phase 1, but the actual middleware lands
  in Phase 4 alongside approvals — they're inseparable in practice.

---

## Dependency Graph

```
Phase 1 Foundation
    │
    ├── Phase 2 Browser end-to-end (one trivial tool)
    │       │
    │       ├── Phase 3 Persistence + observability
    │       │       │
    │       │       └── Phase 4 Approvals + guardrails
    │       │               │
    │       │               ├── Phase 5 Phone bridge (Twilio)
    │       │               │       │
    │       │               │       └── Phase 6 HVAC vertical pack
    │       │               │               │
    │       │               │               ├── Phase 7 Translate mode
    │       │               │               │
    │       │               │               └── Phase 8 Eval harness
    │       │               │                       │
    │       │               │                       └── Phase 9 Polish + ship
```

Phase 7 (Translate) and Phase 8 (Evals) are independent and can run in
parallel after Phase 6.

---

## Task List

### Phase 1: Foundation

#### Task 1: Repo skeleton and docker-compose

**Description:** Create the directory layout from spec §7. Set up
`docker-compose.yml` with Postgres 16 and Redis 7 services. Create
`.env.example` with all required keys.

**Acceptance criteria:**
- [ ] Directory layout matches spec §7.
- [ ] `docker compose up postgres redis` starts both services healthy.
- [ ] `.env.example` lists every variable from spec §8.

**Verification:**
- [ ] `docker compose ps` shows `postgres` and `redis` healthy.
- [ ] `psql` and `redis-cli` connect using values from `.env.example`.

**Dependencies:** None.
**Files likely touched:** `docker-compose.yml`, `.env.example`,
`README.md`, empty package roots.
**Scope:** S

---

#### Task 2: Postgres schema and migrations

**Description:** Set up `alembic` in `core/`. Write the initial
migration creating `conversations`, `turns`, `tool_calls`, `approvals`,
`trace_events` tables exactly as spec §5.

**Acceptance criteria:**
- [ ] `alembic upgrade head` from a clean DB creates all five tables.
- [ ] Indexes exist on `conversation_id` foreign keys and `ts` columns.
- [ ] Forward-only migration; no destructive `down`.

**Verification:**
- [ ] `\d+` in psql shows all columns + types from spec §5.
- [ ] `make migrate` from a fresh DB succeeds.

**Dependencies:** Task 1.
**Files:** `core/alembic/`, `core/alembic.ini`, `Makefile`.
**Scope:** S

---

#### Task 3: Python core skeleton

**Description:** Initialize `core/` with `pyproject.toml`, FastAPI app,
asyncpg connection pool, settings via env, structured JSON logging,
`/healthz` endpoint. No business logic yet.

**Acceptance criteria:**
- [ ] `uv run cockpit-core` starts FastAPI on configured port.
- [ ] `/healthz` returns DB + Redis connectivity status.
- [ ] mypy `--strict` and ruff pass on the skeleton.

**Verification:**
- [ ] `curl localhost:PORT/healthz` returns `{"status": "ok"}`.
- [ ] `make test-core` passes (smoke test only at this stage).

**Dependencies:** Tasks 1, 2.
**Files:** `core/pyproject.toml`, `core/src/cockpit_core/main.py`,
`core/src/cockpit_core/api/health.py`, `core/src/cockpit_core/store/__init__.py`.
**Scope:** S

---

#### Task 4: Python store layer (read/write)

**Description:** Implement async CRUD for `conversations`, `turns`,
`tool_calls`, `approvals`, `trace_events` using raw SQL via asyncpg.
Strict typed dataclasses for rows.

**Acceptance criteria:**
- [ ] One function per table for create / get / update where applicable.
- [ ] Integration tests use a real Postgres test container.
- [ ] All store functions are typed; mypy strict passes.

**Verification:**
- [ ] `make test-core` passes the store integration tests.
- [ ] Round-trip test: write a conversation + 3 turns + 1 tool call,
  read them back, assert deep equality.

**Dependencies:** Task 3.
**Files:** `core/src/cockpit_core/store/*.py`, `core/tests/test_store.py`.
**Scope:** M

---

#### Task 5: Node edge skeleton

**Description:** Initialize `edge/` with TypeScript strict, Fastify,
`ws`, settings via env, structured logging, `/healthz` endpoint.

**Acceptance criteria:**
- [ ] `npm run dev` starts Fastify on configured port with hot reload.
- [ ] `/healthz` returns ok and reports core HTTP reachability.
- [ ] eslint + prettier + tsc strict pass.

**Verification:**
- [ ] `curl localhost:PORT/healthz` returns expected JSON.
- [ ] `make test-edge` passes the skeleton tests.

**Dependencies:** Task 1.
**Files:** `edge/package.json`, `edge/tsconfig.json`,
`edge/src/server.ts`, `edge/src/settings.ts`.
**Scope:** S

---

#### Task 6: Frontend skeleton

**Description:** Initialize `frontend/` with Vite + React 18 +
TypeScript + Tailwind. Basic layout: top nav, main pane, side panel.
Single-operator basic-auth gate using env credentials. No real
features yet.

**Acceptance criteria:**
- [ ] `npm run dev` starts Vite, page loads.
- [ ] Login form blocks access until env-configured creds match.
- [ ] Tailwind classes render correctly.

**Verification:**
- [ ] Manual: open browser, confirm login flow.
- [ ] `npm run build` produces a static dist with no warnings.

**Dependencies:** Task 1.
**Files:** `frontend/package.json`, `frontend/vite.config.ts`,
`frontend/src/App.tsx`, `frontend/src/auth/`.
**Scope:** M

---

### Checkpoint: Foundation

- [ ] `docker compose up` brings up Postgres, Redis, core, edge,
  frontend; all `/healthz` endpoints green.
- [ ] All linters and type checkers pass on all three packages.
- [ ] Store integration tests pass.
- [ ] Human review: directory layout matches spec, conventions are
  consistent across packages.

---

### Phase 2: Browser end-to-end (one trivial tool)

The goal of this phase is to make a voice round-trip work in the
browser, with one trivial tool, **before** any persistence, approvals,
or HVAC content. This proves the OpenAI Realtime + WebRTC integration.

#### Task 7: Agent contract and tool registry

**Description:** Implement the `Agent` and `Tool` Python protocols
from spec §6.1–6.2. Build an in-memory tool registry that an Agent
loads at session start. Add a single trivial tool `get_time()` returning
the current ISO time.

**Acceptance criteria:**
- [ ] `Tool` and `Agent` types match spec §6 exactly.
- [ ] Registry can register, list, and dispatch tools by name.
- [ ] Unit tests cover registration, dispatch, and unknown-tool error.

**Verification:**
- [ ] `make test-core` passes new agent runtime tests.
- [ ] mypy strict passes.

**Dependencies:** Task 4.
**Files:** `core/src/cockpit_core/agent/contract.py`,
`core/src/cockpit_core/agent/registry.py`,
`core/tests/test_agent_runtime.py`.
**Scope:** S

---

#### Task 8: Edge ↔ core HTTP + WS protocol (skeleton)

**Description:** Implement the protocol from spec §6.3. Core exposes
`POST /v1/sessions`, `POST /v1/sessions/{id}/tool-calls`,
`POST /v1/sessions/{id}/end`, and a per-session WebSocket. Edge has a
typed client wrapping all four. Mock the OpenAI Realtime side at this
stage.

**Acceptance criteria:**
- [ ] Edge can create a session, request a tool call, and end the session.
- [ ] WebSocket events flow from core to edge for the three event kinds.
- [ ] Contract tests assert the protocol on both sides.

**Verification:**
- [ ] `make test-core` and `make test-edge` both pass new protocol tests.
- [ ] Manual: trigger a tool call from a curl-driven mock edge, see
  the result returned.

**Dependencies:** Tasks 5, 7.
**Files:** `core/src/cockpit_core/api/sessions.py`,
`edge/src/core-client/index.ts`, contract tests on both sides.
**Scope:** M

---

#### Task 9: OpenAI Realtime session manager (Node)

**Description:** Manage a per-conversation WebSocket to OpenAI
Realtime. Forward audio frames in/out, handle `response.created`,
`response.done`, `function_call`, `transcript.delta` events. When a
function_call event arrives, call the core tool-calls endpoint and
inject the result back via `conversation.item.create`.

**Acceptance criteria:**
- [ ] On session create, a new OpenAI Realtime WS opens.
- [ ] Audio frames received from a test client reach OpenAI; OpenAI's
  audio frames are forwarded back.
- [ ] A `function_call` event triggers a core HTTP call and result injection.

**Verification:**
- [ ] Integration test using a recorded OpenAI Realtime fixture
  player; assert event flow + tool round-trip.
- [ ] Manual: run with a real key, hold a 10s test conversation.

**Dependencies:** Task 8.
**Files:** `edge/src/openai/session.ts`,
`edge/src/openai/events.ts`, `edge/tests/openai-fixtures/`,
`edge/tests/test_session_manager.ts`.
**Scope:** M

---

#### Task 10: WebRTC signaling and browser audio bridge

**Description:** Implement WebRTC offer/answer/ICE on the edge. The
peer connection's audio track flows through the edge to the OpenAI
Realtime session created in Task 9.

**Acceptance criteria:**
- [ ] Browser can establish a WebRTC connection to the edge.
- [ ] Mic audio reaches the OpenAI session; OpenAI's audio reaches the
  browser speaker.
- [ ] Connection survives a 60s test conversation without dropouts.

**Verification:**
- [ ] Manual: open the browser test page, talk, hear the model.
- [ ] Network tab: confirm DTLS-SRTP audio flows.

**Dependencies:** Task 9.
**Files:** `edge/src/webrtc/signaling.ts`,
`edge/src/webrtc/peer.ts`, basic test page in `frontend/src/dev/`.
**Scope:** M

---

#### Task 11: Frontend talk button + transcript

**Description:** Add a "Talk" button on the cockpit main pane that
initiates a session, opens the WebRTC connection, and renders the
live transcript stream from the edge's session WebSocket.

**Acceptance criteria:**
- [ ] Click talk → mic permission → connection established.
- [ ] Live transcript text appears as the user speaks and the model responds.
- [ ] Click stop → session ends cleanly, both sides close.

**Verification:**
- [ ] Manual: full talk-listen-talk cycle in the browser.

**Dependencies:** Tasks 6, 10.
**Files:** `frontend/src/cockpit/Talk.tsx`,
`frontend/src/cockpit/TranscriptView.tsx`.
**Scope:** M

---

#### Task 12: First trivial tool wired end-to-end

**Description:** Register `get_time` in the agent runtime. Configure
the test agent's prompt to mention the tool. Verify a voice question
"what time is it?" triggers the tool, the result is injected, and the
model speaks it back.

**Acceptance criteria:**
- [ ] Voice question triggers a `function_call` event.
- [ ] Core executes `get_time` and returns a result.
- [ ] Model speaks the time back to the user.

**Verification:**
- [ ] Manual: ask "what time is it?", confirm spoken time matches now.
- [ ] Logs show the full event sequence.

**Dependencies:** Task 11.
**Files:** test agent definition, prompt fixture.
**Scope:** S

---

### Checkpoint: Phase 2 — Voice loop works end-to-end

- [ ] A real voice conversation in the browser triggers a real tool
  call against the real OpenAI Realtime API.
- [ ] First-response latency under 1.5s p50 on a local network.
- [ ] No panics, no hung sessions, clean shutdown on browser close.
- [ ] Human review of the OpenAI session manager — this is the
  highest-risk integration; sign off before adding persistence on top.

---

### Phase 3: Persistence and observability

#### Task 13: Conversation lifecycle persistence

**Description:** On `POST /v1/sessions`, write a `conversations` row.
On `POST /v1/sessions/{id}/end`, set `ended_at` and `cost_usd` aggregates.
Wire the agent runtime to use the conversation id throughout.

**Acceptance criteria:**
- [ ] Every started session has a `conversations` row.
- [ ] Ended sessions have `ended_at` set within 1s of end.
- [ ] Tests cover happy path + abrupt disconnect.

**Verification:**
- [ ] `make test-core` passes lifecycle tests.
- [ ] Manual: start + end a session, read row from psql.

**Dependencies:** Task 8.
**Files:** `core/src/cockpit_core/agent/lifecycle.py`,
session API handlers, lifecycle tests.
**Scope:** S

---

#### Task 14: Turn persistence

**Description:** Every transcript delta from the edge results in a
`turns` row. Group consecutive deltas of the same role into a single
turn until role changes.

**Acceptance criteria:**
- [ ] User turns persist with full transcript.
- [ ] Agent turns persist with full transcript.
- [ ] `latency_ms` is set on agent turns (time from user-turn-end to
  first agent audio).

**Verification:**
- [ ] Integration test: run a fixture conversation, assert turn rows
  match expected sequence.

**Dependencies:** Tasks 9, 13.
**Files:** turn-grouping logic in core,
`core/tests/test_turn_persistence.py`.
**Scope:** M

---

#### Task 15: Trace event pipeline

**Description:** Implement the structured tracer per spec §6.4.
Async batched writes to `trace_events`. Drop-with-counter on
backpressure. Emit at every well-defined point: session.start,
turn.start, turn.end, tool.requested, tool.executed, tool.failed,
session.end.

**Acceptance criteria:**
- [ ] All seven event kinds emitted at the right boundaries.
- [ ] Batching reduces write volume (configurable batch size).
- [ ] Dropped-event counter visible in `/healthz`.

**Verification:**
- [ ] Run a fixture session, assert all expected event kinds present
  with correct ordering.

**Dependencies:** Tasks 13, 14.
**Files:** `core/src/cockpit_core/observability/tracer.py`,
`core/src/cockpit_core/observability/sinks.py`,
tracer tests.
**Scope:** M

---

#### Task 16: Cockpit conversation list and trace explorer

**Description:** Frontend page listing recent conversations
(latest 50) and a per-conversation trace view rendering events as a
vertical waterfall with timestamps, latencies, and costs.

**Acceptance criteria:**
- [ ] Conversation list paginates by 25, sortable by start time.
- [ ] Trace view renders all event kinds with appropriate icons.
- [ ] Live updates via WebSocket while a session is active.

**Verification:**
- [ ] Manual: run a live session, watch trace events appear in real time.
- [ ] Open a past session, verify trace renders identically to a fresh load.

**Dependencies:** Task 15.
**Files:** `frontend/src/conversations/ConversationList.tsx`,
`frontend/src/conversations/TraceExplorer.tsx`,
`core/src/cockpit_core/api/conversations.py`.
**Scope:** M

---

### Checkpoint: Phase 3 — Observability is real

- [ ] Every voice interaction produces a queryable trace.
- [ ] Cockpit shows live + historical traces correctly.
- [ ] No trace events are silently dropped under normal load.
- [ ] Human review: trace volume is reasonable, no PII leaks into payloads.

---

### Phase 4: Approvals and guardrails

#### Task 17: Guardrail middleware framework

**Description:** Implement pre-call, post-call, and tool-call hook
points. Plug in a basic PII redactor (regex-driven for emails,
phones, SSNs). Each guardrail decision emits a trace event.

**Acceptance criteria:**
- [ ] Three hook points exist with typed contracts.
- [ ] PII redactor passes a unit-test gold set.
- [ ] Every guardrail invocation emits a trace event.

**Verification:**
- [ ] `make test-core` passes guardrail unit tests.

**Dependencies:** Task 15.
**Files:** `core/src/cockpit_core/guardrails/__init__.py`,
`core/src/cockpit_core/guardrails/pii.py`, tests.
**Scope:** M

---

#### Task 18: Approval state machine + persistence

**Description:** Implement the approval flow: when a tool with
`blast_radius: dangerous` is requested, create an `approvals` row,
hold the tool call in `requested` state, and wait for resolution.
Implement the timeout (default 60s) as an async task.

**Acceptance criteria:**
- [ ] Dangerous tool requests block on approval.
- [ ] Resolutions (approved / denied / timeout) update both
  `approvals` and `tool_calls` rows atomically.
- [ ] State machine rejects illegal transitions.

**Verification:**
- [ ] Unit tests cover every legal and illegal transition.
- [ ] Integration test: dangerous tool request held, then resolved
  via API call, then executed.

**Dependencies:** Task 17.
**Files:** `core/src/cockpit_core/agent/approvals.py`, tests.
**Scope:** M

---

#### Task 19: Redis approval pub/sub

**Description:** Publish approval state changes to a Redis channel.
Subscribers (frontend, edge) receive real-time updates. Backed by the
same `approvals` table — Redis is the notification layer, Postgres is
the truth.

**Acceptance criteria:**
- [ ] On approval request, message published with conversation_id.
- [ ] On resolution, message published with decision.
- [ ] At-least-once delivery is acceptable; duplicates are idempotent.

**Verification:**
- [ ] Integration test: pub-sub round trip with an approval lifecycle.

**Dependencies:** Task 18.
**Files:** `core/src/cockpit_core/observability/notifier.py`, tests.
**Scope:** S

---

#### Task 20: Voice-intent classifier (edge, local)

**Description:** Implement the local voice-intent classifier per spec
§13. A small recognizer (e.g. whisper-tiny via WASM or a Node binding)
plus an exact-phrase matcher per pending tool call. Behind a `Classifier`
interface so an OpenAI variant can swap in.

**Acceptance criteria:**
- [ ] Recognizes the configured approval phrase for the active pending tool.
- [ ] Ignores non-matching speech.
- [ ] Latency under 200ms p95 on a typical operator phrase.

**Verification:**
- [ ] Unit tests with audio fixtures: 20 positive, 20 negative phrases.
- [ ] Manual: speak the configured phrase, see approval resolve.

**Dependencies:** Task 19.
**Files:** `edge/src/voice-intent/classifier.ts`,
`edge/src/voice-intent/whisper.ts`, fixture audio + tests.
**Scope:** M

---

#### Task 21: Cockpit approval queue UI

**Description:** Frontend component listing pending approvals for
active conversations, with one-click approve/deny. Subscribes to the
Redis approval channel via the WebSocket.

**Acceptance criteria:**
- [ ] Pending approvals appear within 500ms of being created.
- [ ] Approve/deny buttons resolve via core API.
- [ ] Resolved approvals leave the queue immediately.

**Verification:**
- [ ] Manual: trigger a dangerous tool from a voice session, click
  approve in cockpit, confirm tool executes.

**Dependencies:** Tasks 19, 20.
**Files:** `frontend/src/approvals/ApprovalQueue.tsx`.
**Scope:** S

---

#### Task 22: End-to-end approval flow test

**Description:** Add a temporary `dangerous_test` tool to the test
agent with an exact phrase "go ahead and do it." Write an integration
test that runs the full flow: voice → tool requested → held → voice
phrase resolves → tool executes.

**Acceptance criteria:**
- [ ] Test passes against a fixture audio replay.
- [ ] Test also passes the cockpit-click resolution path.
- [ ] Both tests run in CI.

**Verification:**
- [ ] `make test-eval` runs the new scenario and passes.

**Dependencies:** Task 21.
**Files:** `core/tests/scenarios/approval_voice.yaml`,
`core/tests/scenarios/approval_click.yaml`, harness scaffolding.
**Scope:** S

---

### Checkpoint: Phase 4 — Approvals work end-to-end

- [ ] A dangerous tool cannot execute without explicit approval.
- [ ] Voice phrase and cockpit click both resolve approvals.
- [ ] Timeouts resolve as `denied` and emit traces.
- [ ] Human review of the guardrail middleware — no path bypasses it.

---

### Phase 5: Phone bridge (Twilio Media Streams)

#### Task 23: Twilio Media Streams handler (Node)

**Description:** Implement the WebSocket endpoint Twilio dials into.
Decode μ-law @ 8kHz, resample to PCM16 @ 24kHz for OpenAI, encode the
return path. Bridge to the OpenAI Realtime session manager from Task 9.

**Acceptance criteria:**
- [ ] Accepts Twilio's media-stream WebSocket protocol.
- [ ] Audio bridges in both directions without buffer underruns.
- [ ] Reconnect logic handles brief disconnects without ending the call.

**Verification:**
- [ ] Integration test using a recorded Twilio Media Stream fixture.
- [ ] Manual: dial a Twilio test number, hear the model respond.

**Dependencies:** Task 9.
**Files:** `edge/src/twilio/media-stream.ts`,
`edge/src/twilio/audio.ts`, `edge/tests/twilio-fixtures/`.
**Scope:** M

---

#### Task 24: Inbound call routing

**Description:** Twilio webhook `/twilio/voice` returns TwiML that
streams the call into the Media Streams endpoint. Map the dialed
number to a vertical (configured in env), and start a conversation
in that vertical.

**Acceptance criteria:**
- [ ] Inbound calls route to the correct vertical based on the called number.
- [ ] If no vertical matches, the call is politely rejected with a TwiML say.
- [ ] Webhook is signed-token-verified.

**Verification:**
- [ ] Integration test: simulated Twilio webhook with a known number
  returns expected TwiML.
- [ ] Manual: real call routes to a session in the configured vertical.

**Dependencies:** Task 23.
**Files:** `edge/src/twilio/webhook.ts`, `edge/src/twilio/routing.ts`.
**Scope:** S

---

#### Task 25: Local-dev tunnel script

**Description:** Add `make tunnel` target running cloudflared (or
ngrok as fallback) to expose the edge's webhook to Twilio. Print the
public URL to use in Twilio number config.

**Acceptance criteria:**
- [ ] `make tunnel` exposes the edge port and prints the public URL.
- [ ] README documents wiring this URL into the Twilio number.

**Verification:**
- [ ] Manual: run tunnel, place a Twilio call, verify it reaches
  local edge.

**Dependencies:** Task 24.
**Files:** `scripts/tunnel.sh`, README ops section.
**Scope:** XS

---

#### Task 26: Phone-side approval flow

**Description:** Confirm the voice-intent classifier from Task 20
works on the phone audio path. Approval phrases spoken on a phone
call resolve the same as in the browser.

**Acceptance criteria:**
- [ ] Classifier accuracy on phone-quality audio matches browser path
  within 5%.
- [ ] End-to-end phone scenario: dangerous tool requested → held →
  resolved by phone voice → executed.

**Verification:**
- [ ] Eval scenario runs against a recorded phone fixture.
- [ ] Manual: real phone call with dangerous test tool.

**Dependencies:** Tasks 20, 24.
**Files:** additional fixture audio, possibly classifier tweaks.
**Scope:** S

---

### Checkpoint: Phase 5 — Phone bridge live

- [ ] A real inbound phone call reaches a vertical agent.
- [ ] Approvals work over the phone surface.
- [ ] Trace pipeline records phone sessions identically to browser sessions.
- [ ] Latency on phone path measured; first response under 1.5s p50.

---

### Phase 6: HVAC vertical pack

#### Task 27: Vertical pack loader

**Description:** Build the loader that reads a directory under
`verticals/<name>/` and assembles an `Agent` instance: parses
`pack.yaml`, loads `prompt.md`, imports `tools.py`, applies
`policy.yaml` and `approvals.yaml`, registers `preambles.yaml`,
hooks `post_call.py`.

**Acceptance criteria:**
- [ ] Loader produces a fully-typed `Agent` from a valid pack directory.
- [ ] Invalid packs fail with clear, line-referenced errors.
- [ ] Hot-reload optional in dev; not required in v1.

**Verification:**
- [ ] Unit tests with three fixture packs (valid, missing field, bad tool).

**Dependencies:** Task 7.
**Files:** `core/src/cockpit_core/verticals/loader.py`, tests.
**Scope:** M

---

#### Task 28: HVAC pack metadata + prompt + policies

**Description:** Author the non-code pack files for HVAC: `pack.yaml`
(name, version, modes, surfaces), `prompt.md` (Aria persona, tone,
preamble guidance), `policy.yaml` (refusal taxonomy, language list),
`approvals.yaml` (dispatch_truck, schedule_move with phrases),
`preambles.yaml` (per-tool canonical phrases).

**Acceptance criteria:**
- [ ] All five files validate against the loader's schema.
- [ ] Prompt is voice-tested in a dry-run conversation.
- [ ] Approval phrases are unique and unambiguous.

**Verification:**
- [ ] Pack loads cleanly via Task 27 loader.
- [ ] Manual: run a session with this pack, no obvious persona issues.

**Dependencies:** Task 27.
**Files:** `verticals/hvac/pack.yaml`, `verticals/hvac/prompt.md`,
`verticals/hvac/policy.yaml`, `verticals/hvac/approvals.yaml`,
`verticals/hvac/preambles.yaml`.
**Scope:** M

---

#### Task 29: HVAC read-only tools

**Description:** Implement `parts_lookup`, `truck_inventory`,
`warranty_check`, `schedule_lookup`, `customer_lookup`. Back them with
a sandbox SQLite or fixture JSON data source for v1 (real CRM
integration is post-v1).

**Acceptance criteria:**
- [ ] Each tool has typed args (JSON schema in spec §6.2 form).
- [ ] Each tool has a unit test covering at least one success case.
- [ ] All five tools have `blast_radius: read`.

**Verification:**
- [ ] `make test-core` passes new tool tests.
- [ ] Manual: ask the agent each question, confirm right tool fires.

**Dependencies:** Task 28.
**Files:** `verticals/hvac/tools.py` (read tools section), fixture
data files, tests.
**Scope:** M

---

#### Task 30: HVAC dangerous tools (approval-gated)

**Description:** Implement `schedule_move` and `dispatch_truck`. Both
have `blast_radius: dangerous` and trigger the approval flow. Back
with the same sandbox source.

**Acceptance criteria:**
- [ ] Both tools require approval per `approvals.yaml`.
- [ ] Successful execution mutates the sandbox state visibly.
- [ ] Denied executions leave state untouched.

**Verification:**
- [ ] Eval scenario: schedule_move approved, schedule_move denied,
  dispatch_truck approved.

**Dependencies:** Tasks 22, 29.
**Files:** `verticals/hvac/tools.py` (dangerous tools), tests.
**Scope:** M

---

#### Task 31: HVAC seed fixtures

**Description:** Build `make seed-hvac`: populates the sandbox with a
realistic parts catalog (~50 parts), 12 trucks with stock, 20
customers with units and warranty records, and 30 future scheduled jobs.

**Acceptance criteria:**
- [ ] `make seed-hvac` is idempotent.
- [ ] Data covers every code path of the HVAC tools.
- [ ] Demo scenarios in §10.6 of spec resolve plausibly against this data.

**Verification:**
- [ ] `make seed-hvac && make test-eval` passes.

**Dependencies:** Task 30.
**Files:** `scripts/seed-hvac.sh`, `verticals/hvac/fixtures/*.json`.
**Scope:** S

---

#### Task 32: post_call.py hook

**Description:** Implement the post-call lifecycle hook. For HVAC,
generate a structured summary (job updates, follow-ups, parts
ordered) and write to a file in `data/post-call/<conv_id>.json`. Real
CRM integration is post-v1 stub.

**Acceptance criteria:**
- [ ] Hook fires after every HVAC conversation ends.
- [ ] Summary captures all tool calls + their results.
- [ ] Errors in the hook do not affect the session — logged + traced.

**Verification:**
- [ ] Run a fixture conversation, confirm the file exists with
  expected contents.

**Dependencies:** Task 31.
**Files:** `verticals/hvac/post_call.py`, tests.
**Scope:** S

---

### Checkpoint: Phase 6 — HVAC vertical complete

- [ ] A real phone call reaches HVAC, runs through tools, gates
  approvals, persists transcripts and post-call summary.
- [ ] At least three demo scenarios runnable end-to-end.
- [ ] Human review: persona feels right, no awkward responses, prompts
  do not leak meta-context.

---

### Phase 7: Translate mode

(Independent of Phase 8. Can run in parallel.)

#### Task 33: Mode switcher API

**Description:** Add `mode.switch` to the core→edge protocol. When
core sends `{ "mode": "translate" }`, edge tears down the current
OpenAI Realtime session and reopens with the Translate model + config.
Conversation id and persisted history continue uninterrupted.

**Acceptance criteria:**
- [ ] Mode switch within an active session takes <2s end-to-end.
- [ ] Audio path remains live; the user hears no full disconnect.
- [ ] Trace records the mode change as an event.

**Verification:**
- [ ] Integration test using mock fixtures for both models.
- [ ] Manual: voice command in HVAC pack triggers translate flip.

**Dependencies:** Task 9.
**Files:** edge session manager, core protocol, tests.
**Scope:** M

---

#### Task 34: Auto-detect language and trigger flip

**Description:** First 3 seconds of inbound audio go through a
language ID classifier (local). If non-English, core requests
`mode.switch` to translate. Configurable per vertical in `pack.yaml`.

**Acceptance criteria:**
- [ ] Language ID accuracy > 90% on a 50-utterance test set
  covering English, Spanish, French.
- [ ] Mode flip happens within 4s of call start when non-English.
- [ ] Flag in `pack.yaml` disables auto-flip if needed.

**Verification:**
- [ ] Eval scenario: Spanish caller flips to translate, English
  caller does not.

**Dependencies:** Task 33.
**Files:** `edge/src/voice-intent/lang-id.ts`, pack schema update,
tests.
**Scope:** M

---

#### Task 35: Frontend mode badge and manual toggle

**Description:** Cockpit shows the active mode for each live session
and lets the operator manually toggle. Toggle calls the same API as
Task 33.

**Acceptance criteria:**
- [ ] Badge updates in real time.
- [ ] Manual toggle works from cockpit during an active call.
- [ ] Disabled state shown if vertical pack forbids switching.

**Verification:**
- [ ] Manual: start a call, click toggle, confirm mode change in trace
  and audio.

**Dependencies:** Tasks 33, 34.
**Files:** `frontend/src/cockpit/ModeBadge.tsx`,
`frontend/src/cockpit/ModeToggle.tsx`.
**Scope:** S

---

### Checkpoint: Phase 7 — Translate mode shipped

- [ ] Translate flips correctly for non-English callers on phone.
- [ ] Operator can manually toggle from the cockpit.
- [ ] Trace records every mode change.

---

### Phase 8: Eval harness

(Independent of Phase 7.)

#### Task 36: Scenario YAML + replay runner

**Description:** Define the scenario YAML schema:
`(audio_input, expected_tool_calls[], expected_approvals[],
expected_transcript_contains[], expected_no_pii_in_log)`. Build a
runner that replays scenarios against the agent core with a fixture
OpenAI Realtime player.

**Acceptance criteria:**
- [ ] Schema documented in `docs/eval-format.md`.
- [ ] Runner outputs pass/fail per assertion with diffs.
- [ ] CLI: `make test-eval [SCENARIO=...]`.

**Verification:**
- [ ] Three smoke scenarios (one each for read, dangerous-approved,
  dangerous-denied) pass.

**Dependencies:** Task 22 (existing scenario plumbing).
**Files:** `core/src/cockpit_core/eval/runner.py`,
`docs/eval-format.md`, smoke scenarios.
**Scope:** M

---

#### Task 37: HVAC scenario suite

**Description:** Author the five required scenarios from spec §10.6:
parts lookup, schedule_move approved, schedule_move denied,
Spanish-flip-to-translate, multi-tool parallel turn. Each scenario
includes a recorded audio input and expected outcomes.

**Acceptance criteria:**
- [ ] All five scenarios present and passing.
- [ ] Each has documented expected tool sequence + approvals.
- [ ] Recorded audio fixtures are deterministic.

**Verification:**
- [ ] `make test-eval` runs all five and passes.

**Dependencies:** Tasks 32, 36.
**Files:** `verticals/hvac/scenarios/*.yaml`, audio fixtures.
**Scope:** M

---

#### Task 38: CI integration

**Description:** Add a CI workflow (GitHub Actions) running unit +
integration + eval suites on every PR. Eval regressions block merge.

**Acceptance criteria:**
- [ ] Workflow runs in under 10 minutes.
- [ ] All three test layers run.
- [ ] Status badges in README.

**Verification:**
- [ ] Open a draft PR, see CI run + green.

**Dependencies:** Task 37.
**Files:** `.github/workflows/ci.yml`, README badges.
**Scope:** S

---

### Checkpoint: Phase 8 — Evals enforced in CI

- [ ] Every merge gates on the HVAC eval suite.
- [ ] Adding a new scenario takes under 15 minutes per the docs.

---

### Phase 9: Polish + ship

#### Task 39: Operator scripts

**Description:** Implement `replay-conversation.py` (rebuild a past
conversation in dev for debugging) and `trace-dump` (text timeline
export). Both surface in `make` targets.

**Acceptance criteria:**
- [ ] `make replay CONV=<uuid>` rehydrates a session in dev mode.
- [ ] `make trace CONV=<uuid>` prints a readable timeline.

**Verification:**
- [ ] Manual: replay a known conversation; output matches its trace.

**Dependencies:** Task 15.
**Files:** `scripts/replay-conversation.py`, `scripts/trace-dump.py`.
**Scope:** S

---

#### Task 40: README, .env.example, ops runbook

**Description:** Write the README covering install, dev, deploy,
Twilio number setup, vertical pack authoring. Polish `.env.example`
with comments. Add `docs/ops.md` covering common failures + recovery.

**Acceptance criteria:**
- [ ] A new dev can clone, follow README, and answer a test call in
  under 30 minutes.
- [ ] `docs/ops.md` covers: stuck approvals, OpenAI rate limits,
  Twilio webhook signing failures, Postgres recovery.

**Verification:**
- [ ] Walk a fresh checkout through the README on a clean machine.

**Dependencies:** Task 39.
**Files:** `README.md`, `.env.example`, `docs/ops.md`.
**Scope:** M

---

#### Task 41: End-to-end smoke test in CI

**Description:** A `make test-e2e` target spins up the full
docker-compose stack, dials the mocked Twilio bridge with a canned
audio file, and asserts the expected tool calls and approval
sequence fire. Runs nightly in CI (not on every PR).

**Acceptance criteria:**
- [ ] Test passes on a clean machine in under 10 minutes.
- [ ] Fails informatively if any service doesn't come up.

**Verification:**
- [ ] Manual: trigger nightly workflow.

**Dependencies:** Task 38.
**Files:** `e2e/`, `.github/workflows/nightly.yml`.
**Scope:** M

---

### Checkpoint: Phase 9 — Ready to ship

- [ ] All 41 tasks closed.
- [ ] All linters, type checkers, tests, evals green in CI.
- [ ] Smoke E2E test green.
- [ ] Demo recorded against HVAC vertical.
- [ ] Human review of the full system + sign-off.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OpenAI Realtime session quirks (resumes, disconnects, event ordering) | High | Phase 2 hits this first on minimal scaffolding. Recorded fixture player isolates regressions. |
| Twilio Media Streams audio quality / packet loss | Medium | Phase 5 uses recorded fixtures + a clear backpressure strategy. Local dev validated before remote. |
| Voice-intent classifier accuracy on phone audio | Medium | Phase-4 unit tests use both browser- and phone-quality fixtures. If accuracy is unacceptable, the swap interface lets us fall back to OpenAI round-trip. |
| WebRTC NAT/Docker networking issues | Medium | Frontend served from a separate container avoids signaling-vs-asset port conflicts. Use host networking for the edge in dev if needed. |
| Latency budget overruns | High | Each phase records a latency measurement at its checkpoint. If p50 exceeds 1.5s after Phase 5, halt feature work and optimize. |
| Approval flow race conditions (concurrent voice + click resolution) | Medium | Approval state machine in Task 18 explicitly tests concurrent resolution paths. |
| Scope creep into multi-tenant / OIDC / cloud deploy | Low–Medium | Spec §12 keeps these out. Plan does not mention them. |

---

## Parallelization Opportunities

When multiple agent sessions or developers are available:

- **Within Phase 1:** Tasks 3 (core), 5 (edge), 6 (frontend) can run
  in parallel after Task 1.
- **Within Phase 3:** Tasks 13, 14, 15 are sequential, but Task 16
  (frontend) can begin in parallel with Task 15 once 14 is done.
- **Phase 7 vs Phase 8:** Independent. Run in parallel.
- **Within Phase 6:** Tasks 28, 29 sequential; Task 31 (seed) and
  Task 32 (post_call) can run after Task 30 in parallel.
- **Frontend tasks** generally can run a step ahead of backend by
  contract-mocking the API.

**Sequential bottlenecks:**

- Tasks 1 → 2 → 3 (DB + migrations + core skeleton).
- Tasks 9 → 10 → 11 → 12 (the OpenAI/WebRTC integration chain).
- Tasks 17 → 18 → 19 → 20 → 21 → 22 (approval flow).

---

## Verification Before Implementation

- [x] Every task has acceptance criteria.
- [x] Every task has a verification step.
- [x] Task dependencies are identified and ordered correctly.
- [x] No task touches more than ~5 files (one or two M tasks brush up
  against this; revisit if they grow during implementation).
- [x] Checkpoints exist between every major phase.
- [ ] **Human has reviewed and approved this plan.**
