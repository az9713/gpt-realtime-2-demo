# Realtime Model Coverage — what we use and how each lands

OpenAI ships **three** models in the GA Realtime family. **All three
are now in active use** in this codebase.

| Model id | Purpose | Where it lands |
|---|---|---|
| `gpt-realtime-2` | Full-featured voice agent: reasons, speaks, calls tools | The cockpit's primary conversational loop |
| `gpt-realtime-translate` | Passthrough translation between two spoken languages | Translate mode (auto + manual flip) |
| `gpt-realtime-whisper` | Streaming transcription only — no reasoning, no audio output | Voicemail, note-taker, bilingual sidecar, audit pipeline, eval synthesis |

Earlier versions of this doc described whisper as a "not used" model
with five proposed features. Those five features are now all
implemented (see [The five whisper-enabled features](#the-five-whisper-enabled-features)
below), and this doc has been rewritten to reflect the current state.

---

## At a glance

```
┌─────────────────────────┐
│  gpt-realtime-2         │  ✅ in use
│  (default conversational│
└────────────┬────────────┘
             │
             ▼
   the cockpit's primary loop
   browser Talk + phone calls
   tools, approvals, persona

┌─────────────────────────┐
│  gpt-realtime-translate │  ✅ in use
└────────────┬────────────┘
             │
             ▼
   translate mode
     • auto-flip on non-English
     • manual cockpit toggle

┌─────────────────────────┐
│  gpt-realtime-whisper   │  ✅ in use across 5 features
└────────────┬────────────┘
             │
             ├── solo: voicemail (after-hours overflow)
             ├── solo: note-taker (silent transcription)
             ├── sidecar: bilingual capture (translate mode)
             ├── sidecar: audit transcripts (always-on for flagged verticals)
             └── offline: synthesize-eval (reads transcripts; no live WS)
```

The whisper model has two operational shapes: **solo** (it's the only
OpenAI WS open for the conversation) and **sidecar** (it runs alongside
a `RealtimeSession`, fed the same audio). One class —
`TranscriptionSession` — implements both.

---

# 1. `gpt-realtime-2` — the conversational default

✅ In active use. Every "Aria" interaction in the cockpit: phone
calls, browser Talk button, every tool dispatch.

## Where it's wired

| Knob | Location |
|---|---|
| Env var | `OPENAI_REALTIME_MODEL=gpt-realtime-2` |
| Edge settings | `edge/src/settings.ts` → `openaiRealtimeModel` |
| Session selection | `edge/src/openai/session.ts` constructor: ternary on `config.mode` |
| WebSocket open | `wss://api.openai.com/v1/realtime?model=<model>` (no `OpenAI-Beta` header on GA) |
| Session.update payload | session.ts `ws.on('open', ...)` — sends GA-shape config |

## What features rely on it

| Feature | Notes |
|---|---|
| Browser cockpit Talk | Default mode for browser surface |
| Phone bridge | Default mode for phone surface |
| Every HVAC tool call | Realtime-2 emits `function_call` items the dispatcher consumes |
| Approval flow | Model preamble *is* the approval phrase |
| Trace pipeline | Each turn produces 5–12 trace events |
| Eval scenarios 01–05 | Drive realtime-2 through the dispatcher path |

---

# 2. `gpt-realtime-translate` — the passthrough translator

✅ In active use. Powers translate mode — both auto-flip on
non-English callers and manual operator toggle.

## Where it's wired

| Knob | Location |
|---|---|
| Env var | `OPENAI_TRANSLATE_MODEL=gpt-realtime-translate` |
| Edge settings | `edge/src/settings.ts` → `openaiTranslateModel` |
| Mode-switch handoff | `RealtimeSession.switchModel('translate')` |
| Auto-flip trigger | `pack.yaml: auto_translate_non_english: true` |
| Auto-flip detector | `edge/src/voice-intent/lang-id.ts` |

## Bilingual capture (Phase 2)

When a session enters translate mode, a `TranscriptionSession`
**sidecar** opens lazily on the first audio frame. Both the
target-language transcript (translate model) and the source-language
transcript (whisper) land in `app.turns` with `turns.model`
distinguishing them.

This is the audit-style capture for translate sessions. See
[concepts/translate-mode.md](../concepts/translate-mode.md) for the
full lifecycle.

---

# 3. `gpt-realtime-whisper` — the transcription specialist

✅ In active use. This is the model behind every silent-transcription
flow.

## Where it's wired

| Knob | Location |
|---|---|
| Env var | `OPENAI_WHISPER_MODEL=gpt-realtime-whisper` |
| Edge settings | `edge/src/settings.ts` → `openaiWhisperModel` |
| Class | `edge/src/openai/transcription.ts` → `TranscriptionSession` |
| WebSocket open | **Different URL** from realtime-2: `wss://api.openai.com/v1/realtime?intent=transcription`. Model id flows in `audio.input.transcription.model`, **not** the URL. |
| Session.update payload | `session.type: "transcription"`; no `output_modalities`, no `tools`, no `instructions`, no `audio.output`, **no `turn_detection`** (whisper rejects it). |

GA distinguishes "realtime sessions" (conversational, audio out, tools)
from "transcription sessions" (whisper-only) at the URL level. Connecting
to `?model=gpt-realtime-whisper` returns *"Passing a transcription
session update event to a realtime session is not allowed."* See
[`docs/ops.md`](../ops.md#whisper-transcription-session--endpoint-quirks)
for the full rejection table.

The `TranscriptionSession` class is mode-agnostic; whether it runs
solo or sidecar is decided by the caller (`signaling.ts`,
`media-stream.ts`, `session.ts`).

## The five whisper-enabled features

### 1 — Voicemail / overflow handler (solo)

**When:** A vertical declares `business_hours` in `pack.yaml` and the
caller dials outside that window.
**What happens:** The Twilio webhook fetches
`GET /v1/verticals/<name>/business-status`; if `open: false` it returns
voicemail TwiML (`<Say>greeting</Say><Connect><Stream
mode=voicemail>`). The edge media-stream handler opens a solo
`TranscriptionSession`. No agent reasoning. After the caller hangs
up, the post_call hook writes a voicemail-shape summary with intent
classification and callback-phone extraction.
**Read:** [concepts/voicemail.md](../concepts/voicemail.md).

### 2 — Note-taker mode (solo)

**When:** A dispatcher presses **Notes only** in the cockpit instead
of **Talk**.
**What happens:** The edge opens a solo `TranscriptionSession`
against `gpt-realtime-whisper` — no `RealtimeSession`, no agent
persona, no tools. Whisper transcribes silently into `app.turns`. A
notetaker post_call summary captures the transcript without a tool
roll-up.
**Read:** [concepts/note-taker.md](../concepts/note-taker.md).

### 3 — Bilingual transcript capture (sidecar)

**When:** A session is in translate mode.
**What happens:** A whisper sidecar opens lazily on the first audio
frame. Both transcript streams (translate target-language, whisper
source-language) persist with distinct `turns.model` tags. This is the
groundwork the audit feature builds on.
**Read:** [concepts/translate-mode.md](../concepts/translate-mode.md#bilingual-capture).

### 4 — Audit transcripts (sidecar always-on)

**When:** A vertical declares `audit_transcripts: true` in
`pack.yaml`.
**What happens:** The whisper sidecar opens **at session start in
parallel** with the primary session (not lazily) — this is the
feature whose latency budget warrants paying setup cost up front. A
nightly `make audit` job diffs agent vs. canonical transcripts per
turn and writes flagged divergences to `app.audit_divergences`.
**Read:** [concepts/audit-transcripts.md](../concepts/audit-transcripts.md).

### 5 — Eval generation from real calls (offline)

**When:** An operator runs `make synthesize-eval CONV=<uuid>`.
**What happens:** The script reads `app.turns` + `app.tool_calls` +
`app.approvals` and emits a Scenario YAML matching the existing eval
schema. The output is a self-passing eval against the same
`run_scenario()` that drives `make test-eval`. v1 reads transcripts
directly (no live whisper) per [SPEC §13.2](../../SPEC.md); v1.5 will
optionally accept a stored audio file and run whisper over it.
**Read:** [guides/synthesize-eval.md](../guides/synthesize-eval.md).

---

## Solo vs sidecar — one class, two shapes

```
SOLO (voicemail, note-taker)
─────────────────────────────
  inbound audio  ─►  TranscriptionSession
                          │
                          ▼
                   POST /transcript (model='whisper')

SIDECAR (translate-bilingual, audit)
─────────────────────────────────────
  inbound audio  ─┬──►  RealtimeSession      ─► agent audio out
                  │            │
                  │            ▼
                  │     POST /transcript (model='gpt-realtime-2|translate')
                  │
                  └──►  TranscriptionSession
                               │
                               ▼
                       POST /transcript (model='whisper')
```

Same audio frames fan out to both — the `RealtimeSession.appendAudio`
implementation forwards to the sidecar when one is attached.

## When does the sidecar open?

`RealtimeSession` decides via `shouldHaveSidecar()` returning true
when *either* `mode === 'translate'` **or** `auditTranscripts === true`:

| Configuration | Sidecar opens? | Timing |
|---|---|---|
| `realtime2` (HVAC default) | No | — |
| `translate` mode | Yes | **Lazy** — on first audio frame |
| `audit_transcripts: true` (any mode) | Yes | **Parallel** — at session start via `Promise.all` |
| Both | Yes | Parallel (audit dominates) |

Lazy open in translate mode is a deliberate latency optimization —
the user has just spoken, the agent is already responding; the sidecar
catches up while the conversation continues, hiding the ~200 ms WS
handshake behind the user's first utterance. For audit-flagged
verticals we pay the cost up-front because completeness matters more
than first-response latency.

---

## The asymmetric mode model

The `mode` field on a conversation has two distinct lifetimes:

| Mode | Mid-call switch allowed? | How activated |
|---|---|---|
| `realtime2` ↔ `translate` | Yes (via `POST /v1/sessions/{id}/mode`) | Auto-detect or operator toggle |
| `voicemail` | **No** — start-time only | Twilio webhook serves voicemail TwiML on after-hours calls |
| `notetaker` | **No** — start-time only | Operator clicks **Notes only** in cockpit |

`ModeSwitchBody.mode` is a Pydantic `Literal["realtime2", "translate"]`
which causes 422 validation errors if voicemail/notetaker are
attempted mid-session — gate enforced by the type system. Voicemail
and notetaker conversations are **agentless**: the
`create_session` endpoint creates the `app.conversations` row but
does **not** attach an agent runtime, load tools, or return a prompt.
See `core/src/cockpit_core/api/sessions.py:_AGENTLESS_MODES`.

---

## Configuration knobs summary

```env
# .env
OPENAI_API_KEY=sk-...
OPENAI_REALTIME_MODEL=gpt-realtime-2
OPENAI_TRANSLATE_MODEL=gpt-realtime-translate
OPENAI_WHISPER_MODEL=gpt-realtime-whisper
```

```yaml
# verticals/<name>/pack.yaml
modes:
  - realtime2
  - translate
  - notetaker      # opts vertical into note-taker mode
  - voicemail      # opts vertical into voicemail mode

auto_translate_non_english: true   # auto-flip to translate

business_hours:                     # voicemail trigger window
  tz: America/Chicago
  open: "09:00"
  close: "17:00"
  days: [1, 2, 3, 4, 5]

voicemail_greeting: voicemail.md    # markdown file in the pack dir

audit_transcripts: false            # set true to enable always-on whisper sidecar
```

---

## Where to read next

- The operational mechanics of each whisper feature:
  - [concepts/voicemail.md](../concepts/voicemail.md)
  - [concepts/note-taker.md](../concepts/note-taker.md)
  - [concepts/audit-transcripts.md](../concepts/audit-transcripts.md)
- Translate mode + bilingual capture: [concepts/translate-mode.md](../concepts/translate-mode.md).
- The model itself: [reference/gpt-realtime-2.md](gpt-realtime-2.md).
- Operator how-tos:
  - [guides/configure-business-hours.md](../guides/configure-business-hours.md)
  - [guides/synthesize-eval.md](../guides/synthesize-eval.md)
