# Key Concepts

Every term that appears in code or other docs without explanation is
defined here. Skim once when you start; come back when something
sounds unfamiliar.

The terms are grouped by topic, then alphabetical within each group.

---

## Core platform terms

**Agent** — The brain that holds a conversation. It has a persona
(name, tone), a tool registry, a guardrail set, and a session lifecycle.
In code: `cockpit_core.agent`. One agent serves all surfaces.

**Approval** — A row in Postgres saying "this dangerous tool call is
waiting for a human yes/no." Created by the agent before executing
any tool with `blast_radius: dangerous`. Resolved by either a spoken
phrase, a cockpit click, or a 60-second timeout (default).
Example: scheduling a service call requires an approval.

**Blast radius** — A label on each tool: `read`, `safe-write`, or
`dangerous`. Read tools (e.g. `parts_lookup`) execute freely. Safe-write
tools execute freely but log audibly. Dangerous tools (e.g.
`dispatch_truck`) require approval before execution.

**Agentless mode** — A session mode where the cockpit creates a
conversation row and bridges audio, but does **not** attach a vertical
agent runtime — no persona, no tools, no guardrails fire. The two
agentless modes are `voicemail` and `notetaker`. Defined in code:
`core/src/cockpit_core/api/sessions.py:_AGENTLESS_MODES`.

**Audit transcripts** — A per-vertical opt-in (`pack.yaml:
audit_transcripts: true`) that runs a `gpt-realtime-whisper` sidecar
always-on alongside the agent. A nightly job diffs the agent's user
transcripts against whisper's canonical record and writes flagged
divergences to `app.audit_divergences`. See
[concepts/audit-transcripts.md](../concepts/audit-transcripts.md).

**Bilingual capture** — When a session enters translate mode, a
whisper sidecar opens lazily and persists the source-language
transcript alongside the translate model's target-language transcript.
Both end up in `app.turns` with distinct `model` tags.

**Business hours** — A per-vertical config block (`pack.yaml:
business_hours: { tz, open, close, days }`) that controls when
voicemail mode activates. Outside the window, inbound calls hit the
voicemail TwiML instead of the agent. IANA timezones, ISO weekdays
(1=Mon, 7=Sun), midnight-wrapping windows supported.

**Conversation** — One end-to-end interaction with a caller or
operator. Has a UUID, a vertical, a surface (phone or browser), a
mode (`realtime2` | `translate` | `voicemail` | `notetaker`), and a
stream of turns/tool calls/trace events. Persisted in
`app.conversations`.

**Core** — The Python agent core (FastAPI + asyncpg). Lives in
`core/`. Owns tool execution, guardrails, persistence, observability.
Does not touch raw audio.

**Cockpit** — The browser UI for the human dispatcher. Live
transcripts, approval queue, trace explorer, voicemail list, audit
divergences. Lives in `frontend/`.

**Divergence** — A row in `app.audit_divergences` flagging a place
where the agent's user-side transcript disagreed with the canonical
whisper transcript on the same utterance. Has a `kind` in
{`paraphrase`, `omission`, `addition`, `mismatch`} and a WER score.
Created by the `make audit` runner. See
[concepts/audit-transcripts.md](../concepts/audit-transcripts.md).

**Edge** — The Node.js transport edge (Fastify + ws). Lives in `edge/`.
Owns WebRTC signaling, Twilio Media Streams, and OpenAI Realtime
WebSocket sessions. Does not execute tools or persist data.

**Guardrail** — A function that runs at one of three hook points:
before user input is sent to the model, before a tool call executes,
or before agent output is shown. Examples: PII redaction, language
detection, safety classifiers.

**Mode** — The session-level model selector. Four values:
`realtime2` (default — agent + tools), `translate` (passthrough
translation), `voicemail` (whisper-only after-hours capture),
`notetaker` (whisper-only silent capture, dispatcher initiated).
Mid-session switches are allowed only between `realtime2` and
`translate`; the other two are start-time only.

**Note-taker mode** — Agentless session: dispatcher takes a call
directly, whisper transcribes silently. New "Notes only" button in
the cockpit's Talk page. See
[concepts/note-taker.md](../concepts/note-taker.md).

**Persona** — The agent's name and voice. The HVAC vertical's
persona is *Aria*. Persona is part of the vertical pack, not the
platform. Agentless modes (voicemail, notetaker) have no persona.

**Preamble** — A short phrase the agent says before invoking a tool,
e.g. "Let me pull up that part." Configured per tool in
`preambles.yaml`. Improves perceived latency by giving the caller
something to listen to while the tool runs.

**Sidecar** (whisper sidecar) — A `TranscriptionSession` instance
opened *alongside* a `RealtimeSession` to capture canonical whisper
transcripts. Used by translate mode (lazy open) and audit-flagged
verticals (parallel open at session start). Audio frames fan out to
both WebSockets.

**Solo (whisper)** — A `TranscriptionSession` opened *instead of* a
`RealtimeSession`. Used by voicemail and note-taker modes. No agent,
no audio output.

**Surface** — A physical channel a human reaches the agent through.
v1 supports `browser` (WebRTC mic/speaker) and `phone` (Twilio
inbound). The agent runs identically on both.

**Tool** — A function the model can call. Has a name, JSON schema for
arguments, a `blast_radius`, an async handler, and an optional preamble.
Example: `parts_lookup(model_number, part_description) -> PartInfo`.

**Tool call** — One invocation of a tool. Has args, a result, a
status (`requested`, `approved`, `denied`, `executed`, `failed`), and
an optional `approval_id`. Persisted in `app.tool_calls`.

**TranscriptionSession** — The shared edge class that wraps a
`gpt-realtime-whisper` WebSocket. Used in two shapes — solo and
sidecar — across five features: voicemail, note-taker, bilingual
capture, audit transcripts, and (offline) eval synthesis. Lives in
`edge/src/openai/transcription.ts`.

**Trace event** — A timestamped record of something that happened in a
conversation: turn boundaries, tool dispatches, guardrail decisions,
approval lifecycle. Async-batched into `app.trace_events`. The cockpit
trace explorer renders these as a vertical waterfall.

**Turn** — One logical utterance from one role: user, agent, tool, or
system. Persisted in `app.turns`. Aggregating consecutive deltas of the
same role into one turn is a deliberate simplification.

**Vertical** / **Vertical pack** — A directory at `verticals/<name>/`
that configures the agent for a specific business. Contains
`pack.yaml`, `prompt.md`, `tools.py`, `policy.yaml`, `approvals.yaml`,
`preambles.yaml`, `post_call.py`, optionally `voicemail.md`. Adding a
vertical does not require modifying the platform.

**Voicemail mode** — Agentless session triggered by Twilio webhook
when a call lands outside the vertical's `business_hours`. A recorded
greeting plays, then whisper captures the caller's message. See
[concepts/voicemail.md](../concepts/voicemail.md).

**WER (Word Error Rate)** — Token-level edit distance normalized by
the longer of the two strings. Used by the audit divergence diff to
score how much the agent's transcript disagrees with whisper's. Same
metric ASR research uses for accuracy.

---

## OpenAI Realtime API terms

**GA Realtime API** — OpenAI's general-availability real-time speech
API, launched in late 2026 alongside the `gpt-realtime-2` model. The
older `wss://api.openai.com/v1/realtime` beta endpoint is now the same
URL but speaks a different event vocabulary (no `OpenAI-Beta` header,
new `session.update` shape). See [reference/gpt-realtime-2.md](../reference/gpt-realtime-2.md).

**gpt-realtime-2** — OpenAI's current production speech-to-speech model.
Takes audio in, emits audio + text + tool-call events out, all over a
single WebSocket. Replaces `gpt-4o-realtime-preview`.

**gpt-realtime-translate** — A sibling model to `gpt-realtime-2`,
optimized as a passthrough translator. The cockpit's "Translate mode"
swaps the active model from realtime-2 to realtime-translate
mid-session.

**gpt-realtime-whisper** — The third GA Realtime model: streaming
transcription only, no reasoning, no audio output. Used in this
codebase for voicemail mode, note-taker mode, the bilingual sidecar
in translate, and the always-on audit sidecar. **Lives at a separate
endpoint** from the conversational realtime URL —
`wss://api.openai.com/v1/realtime?intent=transcription` — with the
model id passed inside the session.update at
`audio.input.transcription.model`. See
[reference/model-feature-map.md](../reference/model-feature-map.md).

**Modalities** / **output_modalities** — Which output channels the
model uses. v1 of this app sets `["audio"]`, meaning the model speaks
its responses. Setting `["text"]` would silence the audio. The GA API
renamed `modalities` to `output_modalities`.

**Server VAD** / **semantic VAD** — *Voice Activity Detection.* The
mechanism by which the API decides when the user has stopped talking
(so it can commit the input buffer and start generating). Server VAD
uses energy thresholds; semantic VAD (the GA default) uses a small
classifier to detect end-of-utterance more naturally.

**Session** (in OpenAI terms) — One open WebSocket from the edge to
OpenAI Realtime, scoped to one conversation. Has its own instructions,
tools, voice, modalities. Configured via the `session.update` client
event after the WS opens.

**Turn detection** — The collection of settings that controls how the
API segments user speech into turns. Lives at
`audio.input.turn_detection` in the GA session shape.

---

## Audio terms

**Base64** — A way of encoding binary data as ASCII text. We base64
audio frames so they fit cleanly into JSON event payloads on the
WebSocket.

**μ-law (mu-law) / G.711** — An 8-bit audio compression format used by
the public switched telephone network (PSTN) and by Twilio's media
streams. Reduces 16-bit linear PCM at 8 kHz to a single byte per
sample using a non-linear quantization curve. Lossy but
intelligible for speech.

**PCM** — *Pulse-code modulation.* The simplest digital audio format:
a stream of 16-bit signed integers, each one a sample of the
waveform. OpenAI Realtime expects PCM at 24 kHz.

**Resampling** — Converting audio from one sample rate to another.
Twilio sends 8 kHz; OpenAI expects 24 kHz, so the edge resamples
both directions. We use linear interpolation, which is "good enough"
for speech (real DSP filtering would be more correct but unnecessary
on band-limited phone audio).

**Sample rate** — How many audio samples per second. 8 kHz = telephone
quality. 16 kHz = early VoIP / podcast. 24 kHz = OpenAI Realtime.
44.1/48 kHz = music.

---

## Networking terms

**HTTP webhook** — A URL that an external service (like Twilio) calls
when something happens. Twilio POSTs to our `/twilio/voice` webhook
when a call comes in; we reply with TwiML telling Twilio what to do.

**ICE / STUN / TURN** — The protocols WebRTC uses to figure out how
two peers (here: the browser and the edge) can talk to each other
through firewalls and NATs. We don't implement these directly in v1
— our browser transport uses a single WebSocket carrying base64 PCM,
not full WebRTC peer connections.

**SIP** — *Session Initiation Protocol.* The signaling protocol used
by traditional VoIP / PBX systems (and by Twilio's Programmable
Voice). We don't speak SIP directly; Twilio handles SIP termination
and hands us audio over WebSocket.

**TwiML** — *Twilio Markup Language.* A small XML dialect Twilio
calls "instructions for what to do with this call." We return TwiML
from our `/twilio/voice` webhook — typically `<Connect><Stream>…</Stream></Connect>`
to bridge into our media-stream WebSocket.

**WebRTC** — A browser standard for real-time peer-to-peer audio,
video, and data. Negotiates a direct UDP-with-encryption connection
between browser and remote peer through ICE/STUN/TURN. Lower latency
and better packet-loss handling than WebSocket-over-TCP. v1 of this
app uses a *WebSocket-with-PCM-frames* approach for simplicity;
true WebRTC integration is a later iteration.

**WebSocket** — A bidirectional, message-oriented connection over a
single long-lived TCP socket. Standardized in RFC 6455. The edge uses
WebSockets to talk to OpenAI, to Twilio, and to the browser cockpit.

---

## Storage / state terms

**Alembic** — Python's standard schema-migration tool, modeled on
Rails-style migrations. Each migration is a Python file that calls
`op.create_table(...)` etc. Runs in order; the version is recorded in
an `alembic_version` table inside the schema.

**asyncpg** — A fast async PostgreSQL driver for Python. We chose it
over psycopg2 + SQLAlchemy ORM for the agent runtime because the
volume is low and the ORM cost isn't earned. SQLAlchemy + psycopg2 are
still used for Alembic.

**Postgres `app` schema** — All cockpit tables live in `app.*`, not
`public.*`. Keeps cockpit data out of the way if the database is
shared with other apps.

**pub/sub** — *Publish/subscribe.* A messaging pattern where senders
publish messages to a "channel" and any number of subscribers receive
them. Redis has built-in pub/sub. We use it to push approval and
trace events from the core to the cockpit's WebSocket in real time.

**Redis** — A fast in-memory key-value store. We use it for pub/sub
notifications and small ephemeral caches; durable data lives in
Postgres.

---

## OpenAI agent-loop terms

**Agent loop** — The "think → call tool → think with result → respond"
cycle the model runs through during a turn. With Realtime, this happens
inside one WebSocket session — the model emits `function_call`
items, you reply with `function_call_output` items, then a new
`response.create` triggers the model to continue.

**Function call** — The model's request to invoke one of the tools you
declared at session-update time. Carries a `call_id`, a tool name,
and a JSON-string `arguments` payload.

**Function call output** — Your reply to a function call. Carries the
same `call_id` and a JSON-string `output` payload. The model uses this
to continue its reasoning.

**Orchestration** — The pattern of routing work between multiple
specialist agents (e.g. a CRM agent, a deploy agent, a lookup agent)
under a single planner. v1 of this app does not implement
multi-specialist orchestration; it has one agent per session. See
[concepts/orchestration.md](../concepts/orchestration.md) for the
design seam.

**Planner / worker** — A pattern where a "planner" agent breaks a task
into sub-tasks and dispatches them to "worker" agents. Each turn in
this app is implicitly a planner+worker pair: the model is the
planner, tool handlers are the workers.

**Realtime-2 (mode)** — In this app, the conversational default mode.
Uses the `gpt-realtime-2` model. Tools, prompts, approvals all active.

**Translate (mode)** — In this app, an alternative session mode that
swaps the model to `gpt-realtime-translate`. Tools and orchestration
are bypassed; the agent acts as a passthrough translator. Triggered
either manually from the cockpit or automatically when the inbound
audio is detected as non-English.

---

## Operational terms

**Cloudflared / ngrok** — Tunneling tools that expose a local port to
a public URL. Used in dev so Twilio's webhooks can reach your laptop.
Run via `make tunnel`.

**Eval** / **scenario eval** — A YAML file describing a test scenario:
inputs, expected tool calls, expected approvals. Run via
`make test-eval`. A regression blocks merge in CI.

**Hot reload** — When the source on your laptop changes, the running
container picks it up automatically (Vite for frontend, tsx for edge,
uvicorn `--reload` for core). Made possible by bind-mounting the
source directory into the container.

**Self-host** / **single-tenant** — One deployment per operator, on
their own server. The opposite of "multi-tenant SaaS" where one
deployment serves many customers. v1 is single-tenant only.
