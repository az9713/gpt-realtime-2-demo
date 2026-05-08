# What is the Voice Operations Cockpit?

A **single voice agent** that picks up your business phone, also lives in
your browser as a "press-to-talk" cockpit, and runs the same tools no
matter which surface the conversation arrives on.

That one sentence hides a lot. The rest of this page unpacks it.

---

## A concrete scenario

You run a small HVAC company. A homeowner calls because their AC is
broken. Today, the receptionist (or a phone tree) has to:

1. Greet the caller.
2. Look up the customer in the CRM.
3. Check whether the unit is still under warranty.
4. See which trucks have a working capacitor in inventory.
5. Find a tech with an open slot tomorrow morning.
6. Ask the dispatcher whether to commit a truck.
7. Move the schedule.
8. Confirm with the caller.

The Voice Operations Cockpit replaces all of that with one **AI
dispatcher named Aria** who:

- Answers the phone (via Twilio).
- Speaks naturally in real time (via OpenAI's GPT-Realtime model).
- Calls the company's tools (`customer_lookup`, `warranty_check`,
  `truck_inventory`, `schedule_lookup`) directly during the call.
- Pauses before any action that mutates state — "scheduling Reggie to
  3 p.m., do I have your okay?" — and waits for the human dispatcher
  to say *Reggie, do it* or click **Approve** in the cockpit.
- Switches into translation mode automatically if the caller speaks
  Spanish.
- Logs every turn, tool call, and decision into a queryable trace
  the dispatcher can scroll back through later.

The same agent — same prompts, same tools, same memory — also runs in
the browser cockpit. The dispatcher can press **Talk** and say
*"Pull up tomorrow's schedule for Aldo"* and Aria does it. If a phone
call has questions the dispatcher should weigh in on, the dispatcher
can see the live transcript, intervene, or take over the call entirely.

That's the whole product.

---

## The mental model

Think of the system as **three layers stacked on top of one another**.

```
┌───────────────────────────────────────────────────────┐
│  SURFACES — where humans show up                     │
│  • Phone (Twilio inbound)   • Browser cockpit         │
│  • (later: meeting bot)                               │
└──────────────────────┬────────────────────────────────┘
                       │
┌──────────────────────▼────────────────────────────────┐
│  EDGE — the audio plane                              │
│  • Bridges audio in/out of OpenAI's Realtime API      │
│  • Speaks Twilio's μ-law on one side, OpenAI's        │
│    PCM-24kHz on the other, translates between them    │
│  • Holds one Realtime WebSocket per active call       │
└──────────────────────┬────────────────────────────────┘
                       │ HTTP for tool calls
                       │ WebSocket for events
┌──────────────────────▼────────────────────────────────┐
│  CORE — the brain                                    │
│  • Tool registry, guardrails, approval state machine  │
│  • Conversation persistence (Postgres)                │
│  • Trace pipeline (one event per decision)            │
│  • Vertical packs (HVAC, real-estate, …)              │
└───────────────────────────────────────────────────────┘
```

**Surfaces** are dumb. They're the physical paths a human can talk to
the agent — a phone call or a microphone in a browser tab. They don't
make decisions; they just carry audio.

**Edge** is the audio plane — written in TypeScript on top of Node.js.
Its only job is to ferry audio between the surface and OpenAI, and to
forward "function calls" (when the model wants to invoke a tool) over
to the core. It doesn't store anything durable. It doesn't decide
anything.

**Core** is the brain — written in Python on top of FastAPI. It runs
the tool implementations, applies guardrails, gates dangerous actions
behind approvals, and writes everything that happens to a Postgres
database for later replay. This is where engineers will spend most of
their time.

---

## Why is it built this way?

Two big decisions shape the architecture. Both are worth understanding
before you read any other doc.

### Decision 1 — Hybrid Python + Node

We could have written everything in one language. We didn't.

- **Audio is latency-sensitive.** When you press Talk and speak, the
  bytes have to reach OpenAI within roughly 100 ms or you'll hear
  yourself echo. Node's WebSocket and event-loop ecosystem is the most
  battle-tested for this kind of work, and Twilio's official SDK
  examples are all in Node.
- **Brains are iteration-heavy.** Tool implementations, guardrails,
  prompt content, and vertical packs change often. Python is where the
  data engineers, ML engineers, and backend engineers already work —
  and it's where the OpenAI Python SDK lives, where SQLAlchemy /
  Alembic for migrations live, where pytest gives the best
  developer ergonomics.

So: Node owns the audio plane (the **edge**), Python owns the brain
(the **core**), and they talk over a small, explicit seam — HTTP for
synchronous tool calls, a per-session WebSocket for events. No shared
memory, no language interop libraries, no cleverness.

### Decision 2 — One agent core, many surfaces

A common pitfall is to build a phone bot, then a browser bot, then a
meeting bot — three separate stacks with three sets of tools and three
prompts that drift apart. We did the opposite:

- One **agent core** with one tool registry, one guardrail layer, one
  approval state machine.
- Multiple **surfaces** that all dispatch into that same core.

This means a tool you write once (e.g. `schedule_move`) works
identically whether the caller is on a phone, in the cockpit, or in a
future meeting bot. It also means the conversation persists across
surfaces — if a phone call ends mid-thought and the dispatcher follows
up in the browser, the agent has the full context.

---

## The HVAC vertical (the v1 implementation)

The platform is generic, but in v1 it ships with **one vertical pack**:
HVAC dispatcher. A "vertical pack" is a directory of YAML and Python
files that configures the agent for a specific business:

```
verticals/hvac/
├── pack.yaml          ← name, version, modes, surfaces
├── prompt.md          ← Aria's persona + voice instructions
├── tools.py           ← parts_lookup, warranty_check, schedule_move, …
├── policy.yaml        ← refusal taxonomy, language list
├── approvals.yaml     ← which tools need approval, what phrase resolves them
├── preambles.yaml     ← what Aria says before invoking each tool
└── post_call.py       ← post-conversation hook (CRM update, etc.)
```

To run a real-estate vertical instead, you'd write a sibling directory
`verticals/realestate/` with its own pack.yaml, prompt, tools, and
approvals. No platform code changes.

---

## How a single phone call flows end-to-end

Let's walk through one real call to make the architecture concrete.

```
1. Homeowner dials the company's Twilio number.

2. Twilio's network receives the call. Twilio's voice webhook
   ("what should I do with this call?") points at our edge service:
       POST https://example.com/twilio/voice
   Our edge replies with TwiML — a tiny XML document — saying
   "open a media stream WebSocket to /twilio/media-stream and
   pass `vertical=hvac` as a parameter."

3. Twilio opens a WebSocket to our edge and starts streaming the
   caller's audio in 20 ms μ-law-encoded frames at 8 kHz.

4. The edge calls the core's POST /v1/sessions endpoint. The core
   loads the HVAC vertical pack, creates a `conversations` row in
   Postgres, and returns the prompt + tool schemas + voice config.

5. The edge opens a second WebSocket — this time outbound to OpenAI's
   Realtime API at wss://api.openai.com/v1/realtime?model=gpt-realtime-2,
   sends a `session.update` event with the prompt and tools, and is
   ready to bridge audio.

6. As the caller speaks, the edge:
   - decodes μ-law into 16-bit PCM,
   - resamples 8 kHz → 24 kHz (OpenAI's expected rate),
   - base64-encodes the result,
   - and sends `input_audio_buffer.append` events to OpenAI.

7. OpenAI's model thinks. When it wants to call a tool — say,
   parts_lookup({"part_description": "capacitor"}) — it emits a
   `response.done` event with a function_call entry in the output
   array. The edge sees this, calls the core's
   POST /v1/sessions/{id}/tool-calls endpoint with the args.

8. The core's dispatcher runs the guardrail middleware, looks up the
   tool by name, runs the handler (which queries the parts catalog
   in JSON fixtures), records the result in Postgres, and returns it.

9. The edge feeds the result back to OpenAI as a
   `conversation.item.create` event with type "function_call_output",
   then asks for a new response.

10. OpenAI generates speech describing the result (e.g. "We've got 12
    of part P-CAP-440-A in stock at $28.50 each"), streaming PCM-24kHz
    audio back to the edge as `response.output_audio.delta` events.

11. The edge resamples 24 kHz → 8 kHz, encodes back to μ-law, and
    sends frames to Twilio. Twilio plays them to the caller.

12. Every step emits a trace event into the Postgres trace_events
    table. The dispatcher's cockpit subscribes to a Redis pub/sub
    channel for that conversation and renders the events live.

13. If the caller hangs up, Twilio sends a `stop` event, the edge
    closes both WebSockets, and the core fires the post_call hook
    (which writes a JSON summary file).
```

That's the whole loop. Every other doc in this folder zooms in on one
piece of it.

---

## How does it all fit together?

Five containers, defined in `docker-compose.yml`:

| Container | Image | Purpose |
|---|---|---|
| `cockpit-postgres` | `postgres:16-alpine` | Durable storage for conversations, turns, tool calls, approvals, traces |
| `cockpit-redis` | `redis:7-alpine` | Pub/sub channel for live cockpit updates; ephemeral session state |
| `cockpit-core` | built from `core/Dockerfile` | Python FastAPI agent core |
| `cockpit-edge` | built from `edge/Dockerfile` | Node.js Fastify transport edge |
| `cockpit-frontend` | built from `frontend/Dockerfile` | React + Vite cockpit UI |

`docker compose up` brings them all up. The first three (postgres,
redis, core) must be healthy before the others can do useful work —
the compose file declares those dependencies, so it handles ordering
automatically.

For local development, all five run on your laptop. For self-hosting in
production, the same compose file deploys to a single VM. There is no
Kubernetes, no service mesh, no multi-region story in v1 — and that's
deliberate (see [SPEC §12](../../SPEC.md)).

---

## What's deliberately NOT in v1

To keep the scope honest, these are out of scope:

- **Outbound calling.** The agent answers calls; it doesn't dial out.
- **Multi-tenant SaaS.** The platform is single-tenant. Each
  deployment serves one operator.
- **HIPAA/SOC 2 readiness.** The telehealth vertical is *designed* in
  the spec to pressure-test the safety story, but is not implemented.
- **OIDC / SSO.** The cockpit uses basic operator-level auth via env
  vars in v1.

These all have clean seams in the architecture so they can be added
later without rewriting anything load-bearing.

---

## Next steps

- If you want a 30-second tour of the words used everywhere → [key-concepts.md](key-concepts.md).
- If you want the full architecture picture → [architecture/system-design.md](../architecture/system-design.md).
- If you want to understand the AI model itself → [reference/gpt-realtime-2.md](../reference/gpt-realtime-2.md).
- If you're going to deploy this and want to understand Twilio → [reference/twilio-integration.md](../reference/twilio-integration.md).
