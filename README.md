# Voice Operations Cockpit

A self-hostable voice agent platform on top of OpenAI's **three GA
Realtime models** — `gpt-realtime-2`, `gpt-realtime-translate`,
`gpt-realtime-whisper`. One agent core, two surfaces (browser cockpit
+ Twilio phone), four operating modes per session, full guardrails +
approvals + audit observability. v1 ships the HVAC dispatcher vertical
as a working reference.

> 📖 Full documentation: [`docs/index.md`](docs/index.md)
> 📋 Spec: [`SPEC.md`](SPEC.md) · Plan: [`PLAN.md`](PLAN.md)
> 🗺️ Model → feature map: [`docs/reference/model-feature-map.md`](docs/reference/model-feature-map.md)

---

## What you can do with it

| Capability | Powered by | What it lets you do |
|---|---|---|
| **Real-time voice agent** with tool calling | `gpt-realtime-2` | Pick up a call, look things up, propose actions, run tools |
| **Spoken approval gates** for dangerous actions | `gpt-realtime-2` | Aria says *"Reggie, do it?"*; dispatcher replies *"Reggie, do it"*; the schedule moves |
| **Cockpit click-to-resolve** approvals | `gpt-realtime-2` | Same gate, resolved by a button instead of a phrase |
| **Auto-translate non-English callers** | `gpt-realtime-translate` | First 3 s of audio classified; mode flips; session continues uninterrupted |
| **Operator-toggle translate mid-call** | `gpt-realtime-translate` | One click flips the active model; conversation ID stable across the swap |
| **Bilingual transcript capture** | `gpt-realtime-translate` + `gpt-realtime-whisper` (sidecar) | Both source-language and target-language transcripts persist for audit |
| **After-hours voicemail overflow** | `gpt-realtime-whisper` (solo) | Calls outside `business_hours` get a recorded greeting + whisper-only capture; no agent risk |
| **Note-taker mode** (silent transcription) | `gpt-realtime-whisper` (solo) | Dispatcher takes a call directly; whisper transcribes silently into the cockpit |
| **Audit transcripts + divergence diff** | `gpt-realtime-whisper` (always-on sidecar) | Verticals opt in via `audit_transcripts: true`; nightly job flags where the agent paraphrased, omitted, or hallucinated |
| **Synthesize evals from real calls** | offline use of transcripts | `make synthesize-eval CONV=<uuid>` turns any past conversation into a regression-net YAML scenario |
| **Live cockpit UI** | — | Talk button, mode badge, approvals queue, voicemails, audit divergences, conversation list, trace explorer |
| **Trace pipeline** | — | Every decision is one timestamped event in `app.trace_events`; cockpit renders a vertical waterfall |
| **Vertical packs** | — | Add a new business (real-estate, telehealth, ...) by writing a directory; no platform code changes |
| **Eval harness** | — | YAML scenarios drive the dispatcher in-process; CI gates merges on regression |

### Model coverage

```
                                              gpt-realtime-2  gpt-realtime-translate  gpt-realtime-whisper
─────────────────────────────────────────────────────────────────────────────────────────────────────────
HVAC dispatcher (browser + phone)                ✓
HVAC tools, approvals, traces                     ✓
Translate mode (manual + auto)                                       ✓
Bilingual transcript capture                                         ✓                       ✓ (sidecar)
Voicemail / overflow handler                                                                  ✓ (solo)
Note-taker mode                                                                               ✓ (solo)
Audit transcripts + divergence diff                                                           ✓ (sidecar)
Synthesize eval from real call                                                                ✓ (offline)
```

Every GA Realtime model has at least one production feature. See
[`docs/reference/model-feature-map.md`](docs/reference/model-feature-map.md)
for an exhaustive mapping with file paths.

---

## Use cases

Concrete scenarios the platform was designed for. Each links to a
worked walk-through in [`docs/use-cases.md`](docs/use-cases.md).

### 🛠️ HVAC dispatcher (the v1 reference vertical)

A homeowner calls about a broken AC. **Aria** (the persona) pulls up
the customer record, checks warranty status, looks up parts in stock,
finds an open slot tomorrow morning, asks the dispatcher *"Reggie,
send the truck?"* — a spoken phrase resolves the dangerous-tool
approval, the truck dispatches, the post-call hook writes a structured
summary.

**Models in use:** `gpt-realtime-2`. **Tools:** `parts_lookup`,
`truck_inventory`, `warranty_check`, `schedule_lookup`,
`customer_lookup`, `schedule_move` (gated), `dispatch_truck` (gated).

### 🌎 Spanish-speaking caller, English-only dispatcher

The caller's first sentence is *"Hola, necesito agendar un servicio."*
Within ~3 seconds the cockpit auto-flips to translate mode. Aria now
relays between Spanish and English. The dispatcher hears English
transcripts and replies in English; the caller hears Spanish. A
whisper sidecar captures the source-language transcript alongside —
the audit-grade record.

**Models in use:** `gpt-realtime-translate` (active),
`gpt-realtime-whisper` (sidecar). **Trigger:** `pack.yaml:
auto_translate_non_english: true`.

### 🌙 After-hours overflow

A caller dials at 2 a.m. The Twilio webhook checks
`business_hours` (per-vertical IANA-tz config), sees the office is
closed, and serves voicemail TwiML instead of the agent TwiML. The
caller hears a recorded greeting, leaves a message; whisper
transcribes; the dispatcher reads the **Voicemails** tab in the
morning. No risk of Aria committing to something at 2 a.m.

**Models in use:** `gpt-realtime-whisper` (solo). **Operator how-to:**
[`docs/guides/configure-business-hours.md`](docs/guides/configure-business-hours.md).

### 📝 Dispatcher takes a call directly (note-taker)

Dispatcher needs to handle a sensitive customer issue themselves.
They click **Notes only** in the cockpit instead of **Talk**. Whisper
silently transcribes the dispatcher's side of the call into
`app.turns`. No agent persona, no tools, no risk of an agent
committing to something on the call's behalf. The transcript appears
in the cockpit alongside Aria-driven calls.

**Models in use:** `gpt-realtime-whisper` (solo).

### 🔒 Audit-grade compliance (telehealth-class verticals)

A regulated vertical sets `audit_transcripts: true` in its
`pack.yaml`. From now on, every session opens whisper as an always-on
sidecar in parallel with the agent. A nightly `make audit` job diffs
the agent's user-side transcripts against whisper's canonical record.
Divergences (paraphrase, omission, addition, mismatch) land in
`app.audit_divergences` and the cockpit's **Audit** tab — answering
the central compliance question: *did the agent paraphrase, omit, or
hallucinate?*

**Models in use:** `gpt-realtime-2` (or translate) + `gpt-realtime-whisper`
(always-on sidecar). **Concept doc:**
[`docs/concepts/audit-transcripts.md`](docs/concepts/audit-transcripts.md).

### 🧪 Bug → eval, in 30 seconds

A user reports a bug. The dispatcher finds the offending conversation
in `/conversations`, runs `make synthesize-eval CONV=<uuid>`, and
gets a runnable YAML scenario under
`verticals/<vertical>/scenarios/`. The fix lands; the new scenario
goes into CI's `make test-eval`; that bug can't regress silently
again.

**Models in use:** none live — reads `app.turns` + `app.tool_calls`
directly. **Operator how-to:**
[`docs/guides/synthesize-eval.md`](docs/guides/synthesize-eval.md).

---

## Stack

- **Core (Python 3.11):** FastAPI + asyncpg + alembic + structlog +
  pydantic. Agent runtime, tool registry, guardrails, persistence,
  observability, audit divergence diff, eval synthesizer.
- **Edge (Node 20 + TS):** Fastify + ws + undici + pino + twilio.
  WebRTC signaling, Twilio Media Streams, OpenAI Realtime session
  manager (`RealtimeSession`), whisper transcription session
  (`TranscriptionSession`), μ-law ↔ PCM resampler.
- **Frontend (React 18 + Vite + Tailwind):** Cockpit UI — Talk,
  Approvals queue, Voicemails, Audit divergences, Conversation
  list, Trace explorer.
- **Storage:** Postgres 16 (durable: 6 tables) + Redis 7 (pub/sub +
  ephemeral).
- **Telephony:** Twilio Programmable Voice + Media Streams.
- **AI:** OpenAI GA Realtime — `gpt-realtime-2`,
  `gpt-realtime-translate`, `gpt-realtime-whisper`.
- **Packaging:** docker-compose (5 services) + GitHub Actions CI.

Full per-package rationale: [`docs/reference/stack.md`](docs/reference/stack.md).

---

## Quick start

```bash
# 1. Configure
cp .env.example .env
# fill in OPENAI_API_KEY, TWILIO_*, COCKPIT_OPERATOR_PASSWORD

# 2. Bring it up
make build
make up
make migrate          # apply 3 alembic migrations
make seed-hvac        # load HVAC fixtures (parts, trucks, customers, ...)

# 3. Open the cockpit
#    http://localhost:5173
#    sign in with COCKPIT_OPERATOR_USER / COCKPIT_OPERATOR_PASSWORD
```

For phone calls, also: `make tunnel` (exposes the edge to Twilio via
cloudflared/ngrok), then point your Twilio number's voice webhook at
the printed public URL. Walk-through in
[`docs/reference/twilio-integration.md`](docs/reference/twilio-integration.md).

---

## Common commands

```bash
make dev                       # docker compose up (foreground)
make up / make down            # start / stop the stack
make ps                        # container status
make logs                      # tail all service logs

make migrate                   # alembic upgrade head
make seed-hvac                 # load HVAC fixtures

make test                      # full suite — Python + Node
make test-core                 # Python only
make test-edge                 # Node only
make test-eval                 # scenario evals (8 HVAC scenarios)

make tunnel                    # cloudflared tunnel for Twilio
make replay CONV=<uuid>        # text replay of a past conversation
make trace CONV=<uuid>         # trace event timeline

make audit                     # nightly: diff agent vs canonical transcripts
make synthesize-eval CONV=<u>  # turn a real call into an eval scenario
```

`make help` lists everything.

---

## Repo layout

```
core/             Python agent core (FastAPI, asyncpg)
  src/cockpit_core/
    api/          health, sessions, conversations, approvals, verticals, audits
    agent/        contract, registry, dispatch, approvals, runtime, lifecycle
    guardrails/   middleware, pii redactor
    store/        per-table asyncpg helpers (incl. audit_divergences)
    observability/ tracer, sinks, notifier, audit divergence diff
    verticals/    pack loader, business_hours predicate
    eval/         scenario runner, eval-synthesis from real calls
  alembic/        3 migrations: initial / widen modes / audit divergences
  tests/

edge/             Node transport edge (Fastify, ws)
  src/
    openai/       RealtimeSession (agent), TranscriptionSession (whisper),
                  events, sessions-registry
    twilio/       webhook, media-stream, routing (TwiML), audio (μ-law/PCM)
    webrtc/       browser audio bridge (signaling)
    voice-intent/ phrase classifier, language-id
    core-client/  HTTP + WS client to the core
  tests/          incl. transcription, sidecar, voicemail-routing tests

frontend/         React cockpit (Vite, Tailwind)
  src/
    cockpit/      Talk + Notes-only buttons, mode badge, transcript view
    approvals/    pending-approval queue with one-click resolve
    voicemails/   list of after-hours captures
    audit/        list of flagged transcript divergences
    conversations/ list + trace explorer

verticals/hvac/   v1 reference vertical
  pack.yaml       (modes, business_hours, audit_transcripts)
  prompt.md, policy.yaml, approvals.yaml, preambles.yaml
  voicemail.md    after-hours greeting
  tools.py, post_call.py, sandbox.py, fixtures/, scenarios/ (8 evals)

scripts/          seed-hvac, tunnel, replay-conversation, trace-dump,
                  audit-divergences, synthesize-eval
infra/            Postgres init, nginx config
docs/             21 doc files — start at docs/index.md
e2e/              end-to-end smoke test
```

Full architecture diagram + decision rationale:
[`docs/architecture/system-design.md`](docs/architecture/system-design.md).

---

## Documentation map

The `docs/` folder is structured for both new readers and reference
lookups. Recommended entry points:

| Goal | Read |
|---|---|
| Just got here, want the mental model | [`docs/overview/what-is-this.md`](docs/overview/what-is-this.md) |
| See concrete worked examples (UI clicks + terminal + Claude Code) | [`docs/use-cases.md`](docs/use-cases.md) |
| Look up a term used in code | [`docs/overview/key-concepts.md`](docs/overview/key-concepts.md) |
| Map any model to the features that use it | [`docs/reference/model-feature-map.md`](docs/reference/model-feature-map.md) |
| Deep-dive on the GA Realtime API itself | [`docs/reference/gpt-realtime-2.md`](docs/reference/gpt-realtime-2.md) |
| End-to-end Twilio integration walk-through | [`docs/reference/twilio-integration.md`](docs/reference/twilio-integration.md) |
| **What's tested + coverage matrix + known gaps** | [`docs/testing.md`](docs/testing.md) |
| Operations runbook | [`docs/ops.md`](docs/ops.md) |

Concept docs cover each subsystem in depth — voice agents, realtime
conversations, WebRTC, WebSocket, prompting, running agents,
orchestration, guardrails-approvals, integrations-observability,
translate mode, voicemail, note-taker, and audit transcripts. See
[`docs/index.md`](docs/index.md) for the full table of contents.

---

## Status

- ✅ All 9 build phases complete (41 tasks per [`PLAN.md`](PLAN.md))
- ✅ All 6 whisper-feature phases complete
- ✅ 61 Python tests + 27 Node tests passing
- ✅ 8 HVAC scenario evals passing (incl. translate-bilingual,
  notetaker, voicemail-after-hours)
- ✅ ruff + tsc clean
- ✅ 3 alembic migrations applied (head: `0003_audit_divergences`)
- ✅ Three Realtime models in active use:
  - `gpt-realtime-2` at `wss://api.openai.com/v1/realtime?model=gpt-realtime-2`
  - `gpt-realtime-translate` at `wss://api.openai.com/v1/realtime?model=gpt-realtime-translate`
  - `gpt-realtime-whisper` at `wss://api.openai.com/v1/realtime?intent=transcription` (live handshake confirmed)
- ✅ 5 cockpit routes (Talk · Approvals · Voicemails · Audit · Conversations) all return HTTP 200
- ✅ Browser-driven feature test pass complete — see [`docs/testing.md`](docs/testing.md)
- ✅ 10-step manual UI click-path test plan documented and re-runnable per change ([`docs/testing.md`](docs/testing.md#manual-ui-click-path-test-10-steps))
- ✅ Realtime-2 agent self-loop / "cannot stop talking" bug fixed in `frontend/src/cockpit/TalkPage.tsx`: removed the manual `audio.commit` timer that raced with `semantic_vad`, added playback-context teardown on **Stop**, and added a half-duplex gate to prevent speaker→mic echo from re-triggering server VAD ([`docs/ops.md`](docs/ops.md#agent-cannot-stop-talking--self-looping))

For the full test-coverage matrix, gaps inventory, and how to
reproduce every layer locally, see [`docs/testing.md`](docs/testing.md).

---

## Operations

Phone setup, common failures, recovery procedures:
[`docs/ops.md`](docs/ops.md).
