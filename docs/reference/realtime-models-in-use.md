# Realtime Model Coverage — what we use, what we don't, and what we'd add

OpenAI ships **three** models in the GA Realtime family:

| Model id | What it does |
|---|---|
| `gpt-realtime-2` | Full-featured voice agent. Reasons, speaks, calls tools. |
| `gpt-realtime-translate` | Passthrough translation between two spoken languages. |
| `gpt-realtime-whisper` | Streaming transcription. No reasoning, no audio output. |

This codebase uses **two of the three**. This doc explains how the
two are wired up, why the third isn't, and what concrete features we
could add to bring it in.

---

## Quick map

```
                  ┌─────────────────────┐
                  │  gpt-realtime-2     │  ✅ in use
                  │  (default mode)     │
                  └─────────────────────┘
                            │
                  ┌─────────▼───────────┐
                  │  Cockpit's          │
                  │  conversational     │
                  │  loop               │
                  └─────────────────────┘

                  ┌─────────────────────┐
                  │  gpt-realtime-      │  ✅ in use
                  │  translate          │
                  └─────────────────────┘
                            │
                  ┌─────────▼───────────┐
                  │  Translate mode     │
                  │  (auto + manual     │
                  │  flip)              │
                  └─────────────────────┘

                  ┌─────────────────────┐
                  │  gpt-realtime-      │  ❌ not used
                  │  whisper            │
                  └─────────────────────┘
                            │
                  ┌─────────▼───────────┐
                  │  Suggested features │
                  │  (see below)        │
                  └─────────────────────┘
```

---

# 1. `gpt-realtime-2` — the conversational default

✅ **In active use.** This is the model behind every "Aria" interaction
in the cockpit: phone calls, browser cockpit talk button, every tool
dispatch.

## Where it's wired

### Configuration

Two places set the model id:

```bash
# .env / .env.example
OPENAI_REALTIME_MODEL=gpt-realtime-2
```

```typescript
// edge/src/settings.ts
export interface Settings {
  ...
  openaiRealtimeModel: string;
}
export function loadSettings(): Settings {
  return {
    ...
    openaiRealtimeModel: process.env.OPENAI_REALTIME_MODEL ?? 'gpt-realtime-2',
    ...
  };
}
```

### Session selection

The model is chosen *per session* based on the conversation's `mode`:

```typescript
// edge/src/openai/session.ts (constructor)
this.model =
  config.mode === 'translate'
    ? settings.openaiTranslateModel       // gpt-realtime-translate
    : settings.openaiRealtimeModel;       // gpt-realtime-2  ← default
```

The default `mode` is `realtime2`, set in the core's session-create
endpoint:

```python
# core/src/cockpit_core/api/sessions.py
class CreateSessionBody(BaseModel):
    ...
    mode: Literal["realtime2", "translate"] = "realtime2"
```

So unless something explicitly opts into translate, you get
`gpt-realtime-2`.

### WebSocket open

```typescript
// edge/src/openai/session.ts (open method)
const url = `wss://api.openai.com/v1/realtime?model=${encodeURIComponent(this.model)}`;
const ws = new WebSocket(url, {
  headers: { Authorization: `Bearer ${this.settings.openaiApiKey}` },
});
```

### Session.update

The full GA-shape session config sent on open:

```typescript
this.send({
  type: 'session.update',
  session: {
    type: 'realtime',
    model: this.model,
    instructions: this.config.prompt,        // from vertical pack prompt.md
    output_modalities: ['audio'],
    tools: this.config.tools,                // serialized vertical tool registry
    audio: {
      input: {
        format: { type: 'audio/pcm', rate: 24_000 },
        turn_detection: { type: 'semantic_vad' },
        transcription: { model: 'whisper-1' },
      },
      output: {
        format: { type: 'audio/pcm', rate: 24_000 },
        voice: this.config.voice,            // OPENAI_VOICE env, default 'alloy'
      },
    },
  },
});
```

## What features rely on it

| Feature | File | Notes |
|---|---|---|
| Browser cockpit Talk | `frontend/src/cockpit/TalkPage.tsx` → `edge/src/webrtc/signaling.ts` | Default mode for browser surface |
| Phone bridge | `edge/src/twilio/media-stream.ts` | Default mode for phone surface |
| Every HVAC tool call | `verticals/hvac/tools.py` | Realtime-2 emits `function_call` items the dispatcher consumes |
| Approval flow | `core/src/cockpit_core/agent/approvals.py` | The model's preamble *is* the approval phrase |
| Trace pipeline | `core/src/cockpit_core/observability/tracer.py` | Every realtime-2 turn produces 5-12 trace events |
| All five HVAC eval scenarios | `verticals/hvac/scenarios/*.yaml` | Eval harness drives realtime-2 paths |

## Operating notes

- **Reasoning effort.** OpenAI recommends `reasoning.effort: 'low'` for
  production. v1 of this codebase doesn't set it explicitly; the
  model's default is fine for HVAC complexity. Add it under `session`
  if you have measured cost or latency pressure.
- **Tool count.** v1 has 7 HVAC tools. Quality stays clean up to
  ~20 tools; beyond that the model picks wrong ones more often.
- **Voice.** `OPENAI_VOICE` in `.env`. Default `alloy`. Available:
  `alloy`, `ash`, `ballad`, `coral`, `echo`, `marin`, `sage`,
  `shimmer`, `verse`.
- **Latency target.** First-response p50 under 1.5 s on a local
  network. Check `make trace CONV=<uuid>` for any conversation; the
  delta from `turn.user` → `turn.agent` is your headline metric.

---

# 2. `gpt-realtime-translate` — the passthrough translator

✅ **In active use.** Powers the cockpit's "Translate mode" — both the
manual operator toggle and the automatic flip on non-English callers.

## Where it's wired

### Configuration

```bash
# .env / .env.example
OPENAI_TRANSLATE_MODEL=gpt-realtime-translate
```

```typescript
// edge/src/settings.ts
openaiTranslateModel: process.env.OPENAI_TRANSLATE_MODEL ?? 'gpt-realtime-translate',
```

### Mode-switch handoff

```typescript
// edge/src/openai/session.ts
async switchModel(mode: 'realtime2' | 'translate'): Promise<void> {
  const newModel = mode === 'translate'
    ? this.settings.openaiTranslateModel
    : this.settings.openaiRealtimeModel;
  if (newModel === this.model) return;
  this.close();           // tear down current OpenAI WS
  this.model = newModel;
  await this.open();      // reopen against the new model id
}
```

The conversation ID is unchanged across the swap; durable state in
Postgres continues uninterrupted (see
[realtime-conversations.md](../concepts/realtime-conversations.md)).

### Auto-flip trigger

Configured per vertical pack:

```yaml
# verticals/hvac/pack.yaml
auto_translate_non_english: true
```

The edge's language-id classifier (`edge/src/voice-intent/lang-id.ts`)
inspects the first ~3 seconds of recognized transcript. If it
returns `es`, `fr`, or any non-`en` value, the edge calls
`coreClient.switchMode('translate')` and the swap kicks in.

### Manual flip

The cockpit's mode toggle button posts to the core:

```typescript
// core/src/cockpit_core/api/sessions.py
@router.post("/{conversation_id}/mode")
async def post_mode_switch(conversation_id: str, body: ModeSwitchBody) -> dict[str, str]:
    if get_runtime(conversation_id) is None:
        raise HTTPException(404, ...)
    await switch_mode(conversation_id, mode=body.mode)
    await publish_session_event(...)
    return {"status": "ok", "mode": body.mode}
```

Which publishes a `mode.switch` event over the per-session Redis
channel; the edge's session listener reacts and calls
`session.switchModel(...)`.

## What features rely on it

| Feature | File | Notes |
|---|---|---|
| Auto translate flip | `edge/src/voice-intent/lang-id.ts` + the edge's session manager | Happens within ~4 s of a non-English start |
| Manual translate toggle | `frontend/src/cockpit/ModeToggle.tsx` | Operator clicks "Switch to Translate" / "Switch to Realtime" in the cockpit |
| Mode badge | `frontend/src/cockpit/ModeBadge.tsx` | Shows "REALTIME-2" or "TRANSLATE" in real time |
| Eval scenario `04_spanish_translate_flip` | `verticals/hvac/scenarios/04_spanish_translate_flip.yaml` | Confirms the flip happens correctly under test |
| Trace event `mode.switch` | `core/src/cockpit_core/agent/lifecycle.py` | Records the boundary in the timeline |

## Operating notes

- **It does not call tools.** Per OpenAI: this model is a
  passthrough translator with no agent turn lifecycle. Don't try to
  configure tools on it; they'll be ignored.
- **The mode swap takes ~1-2 s.** OpenAI WS reopens; the user may
  hear a brief pause. The trace records the swap as a single event.
- **Conversation ID stays stable.** The cockpit's trace explorer
  shows the whole call (pre- and post-flip) on one timeline.

---

# 3. `gpt-realtime-whisper` — the streaming transcriber

❌ **Not used in v1.**

This model is purpose-built for live transcription: audio in, text
out, no reasoning, no spoken response, no tool calls. It's the
transcription specialist of the Realtime family.

## Why we don't use it today

- For **conversational sessions**, `gpt-realtime-2` already returns
  user transcripts via the `audio.input.transcription` config we
  set in `session.update`. So the durable transcript columns
  (`turns.transcript`) get populated from the conversational path
  for free.
- For **translate sessions**, `gpt-realtime-translate` returns the
  *target-language* transcript natively. We don't currently capture
  the *source-language* transcript separately, but that's the only
  gap, and it's small.

So in v1 we don't have a use case that *requires* a separate
transcription-only model.

But we have several use cases that would benefit from one. Each is a
clean additive feature — no platform refactors needed; mostly new
files in the edge + a small migration.

---

## Suggested features that bring `gpt-realtime-whisper` in

The five features below are roughly ordered by leverage (what we'd
build first).

### Suggestion 1 — Voicemail / leave-a-message overflow

**Problem.** When the dispatcher is unavailable (after hours, on a
break, on another call), incoming calls today get the same Aria
treatment with full tool access. We don't want Aria committing to
schedule changes when there's no human in the loop. We *do* want to
capture the message for the dispatcher.

**Solution.** A new conversation `mode = "voicemail"`. The edge opens
a `gpt-realtime-whisper` WebSocket instead of `gpt-realtime-2`.
Aria is replaced by a recorded greeting (Twilio TwiML `<Say>` /
`<Play>`). The whisper model captures the caller's full message as
streaming text. When they hang up, the post-call hook writes a
formatted "voicemail" entry — transcript + extracted intent (parts,
schedule, complaint) — and notifies the dispatcher.

**Why whisper, not realtime-2.** Cheaper (no reasoning tokens), no
risk of accidental tool calls, no risk of hallucinated commitments.
A dedicated transcription model is exactly what voicemail needs.

**Where it lands.**

| File | Change |
|---|---|
| `core/src/cockpit_core/store/conversations.py` | Add `"voicemail"` to the `mode` constraint |
| `core/alembic/versions/...` | New migration relaxing the mode CHECK constraint |
| `edge/src/openai/session.ts` | Add a `voicemail` branch in `switchModel`, point to `gpt-realtime-whisper` |
| `edge/src/twilio/routing.ts` | Detect after-hours via env config; return TwiML that plays a greeting and then opens the media stream in voicemail mode |
| `verticals/hvac/voicemail.md` | The greeting script |
| Cockpit | New "Voicemails" tab listing recent voicemails with the transcript |

**Cost framing.** Most overflow calls today either get hung up on or
are mishandled by Aria. Whisper-only voicemails are nearly free per
call and recoverable later.

---

### Suggestion 2 — Bilingual transcript capture during translate mode

**Problem.** During translate mode we record the *target-language*
transcript (what the dispatcher hears) but not the *source-language*
transcript (what the caller actually said). For audit and compliance
this is a gap.

**Solution.** When a session enters translate mode, the edge opens a
*second* WebSocket — to `gpt-realtime-whisper` — fed with the same
inbound audio. Whisper produces the source-language transcript;
translate produces the target-language transcript. Both land in
`app.turns` with different `model` annotations.

**Why whisper, not realtime-2.** We need the raw words, not a
re-interpretation. Whisper is purpose-built for this.

**Where it lands.**

| File | Change |
|---|---|
| `edge/src/openai/transcript-companion.ts` | New file. A `TranscriptionCompanion` class wrapping a whisper WebSocket. |
| `edge/src/openai/session.ts` | When mode flips to translate, instantiate the companion alongside. Pipe inbound audio frames to both. |
| `core/src/cockpit_core/store/turns.py` | The `model` column already exists; populate it with `'whisper'` for these turns. |
| Cockpit `TraceExplorerPage.tsx` | Render bilingual turns side-by-side when present. |

**Cost framing.** Whisper runs in parallel with translate, doubling
the audio-input cost during translate mode only. For verticals where
audit matters (telehealth, finance), this is worth it.

---

### Suggestion 3 — Background note-taker for human-to-human calls

**Problem.** When the dispatcher takes a call directly (from the
browser cockpit, not via Aria), there's no transcript captured at
all. Notes get lost.

**Solution.** A new cockpit toggle: **Note-taker mode**. The
dispatcher presses Talk; instead of opening a `gpt-realtime-2`
session, the edge opens a `gpt-realtime-whisper` session. The
dispatcher converses with the caller as themselves; whisper
silently transcribes both sides into `app.turns`. After the call,
the dispatcher gets a clean transcript in the conversation detail
view.

**Why whisper, not realtime-2.** The agent is *not* part of this
conversation. Reasoning would actively get in the way. Whisper is
the silent observer this needs.

**Where it lands.**

| File | Change |
|---|---|
| `core/src/cockpit_core/store/conversations.py` | Add `"notetaker"` to the `mode` constraint |
| `frontend/src/cockpit/TalkPage.tsx` | A second "Notes only" button alongside Talk |
| `edge/src/webrtc/signaling.ts` | Branch on the mode in the URL query; `mode=notetaker` opens whisper |
| `verticals/hvac/post_call.py` | Different summarization template for note-taker calls (just transcript, no tool roll-up) |

**Cost framing.** Whisper is significantly cheaper than realtime-2.
A 10-minute human-to-human call is a small fraction of an Aria call
of the same length.

---

### Suggestion 4 — Eval generation from real recorded calls

**Problem.** Writing eval scenarios by hand is slow. We have 5
scenarios in `verticals/hvac/scenarios/`. We'd want hundreds.

**Solution.** A `make synthesize-eval CONV=<uuid>` script that:

1. Takes a past conversation that had ideal behavior (per the
   dispatcher's review).
2. Pulls its audio (if we ever store audio — see suggestion 5) or
   pulls its transcript from `app.turns`.
3. If audio: runs `gpt-realtime-whisper` over it to produce a
   high-fidelity transcript that can be used as `user_inputs` in a
   YAML scenario.
4. Writes a new file under `verticals/<vertical>/scenarios/`
   pre-filled with the user inputs and expected tool calls
   (extracted from `app.tool_calls`).

The dispatcher reviews/edits, commits.

**Why whisper, not realtime-2.** We need a clean transcript of what
the user actually said, not an interpretive replay. Whisper is the
right tool.

**Where it lands.**

| File | Change |
|---|---|
| `scripts/synthesize-eval.py` | New operator script |
| `core/src/cockpit_core/eval/synthesize.py` | The transcript-to-YAML logic |

**Cost framing.** Whisper is cheap; one batch run produces dozens of
eval scenarios. Eval coverage is the highest-leverage place to spend
on quality, so this pays for itself fast.

---

### Suggestion 5 — Compliance-grade audit transcripts

**Problem.** SPEC §13.2 reserves `turns.audio_uri` for a future
S3-style backend, "when a vertical (e.g. telehealth) requires it."
For verticals subject to compliance (HIPAA, FCA, FINRA), we need
*audio + transcript* with chain-of-custody.

**Solution.** When a vertical's `pack.yaml` declares
`audit_transcripts: true`, every conversation runs whisper alongside
realtime-2. Whisper's transcript becomes the canonical record;
realtime-2's transcripts are the agent's view. The audit pipeline
diffs the two — any divergence (the agent paraphrased, the agent
omitted, the agent hallucinated) is flagged.

**Why whisper, not realtime-2.** Whisper is the ground truth: it
produces a verbatim transcript of what was actually said, with no
agent-side interpretation in the loop.

**Where it lands.**

| File | Change |
|---|---|
| `verticals/<name>/pack.yaml` | Schema gains `audit_transcripts: bool` |
| `core/src/cockpit_core/verticals/loader.py` | Surface that flag |
| `edge/src/openai/transcript-companion.ts` | Same companion as suggestion 2, but always-on for audit verticals |
| `core/src/cockpit_core/observability/audit.py` | New file: nightly job that diffs canonical vs. agent transcripts and flags divergences |
| Cockpit | New "Audit divergences" tab |

**Cost framing.** For non-audit verticals (HVAC), feature is off; no
extra cost. For audit verticals (telehealth), the doubled audio cost
is the cost of doing business.

---

## Combined picture

If we land all five suggestions, the model usage map fills in:

```
                  ┌─────────────────────┐
                  │  gpt-realtime-2     │  ✅ in use
                  └─────────────────────┘
                            ↓
                  ┌─────────────────────┐
                  │  gpt-realtime-      │  ✅ in use
                  │  translate          │
                  └─────────────────────┘
                            ↓
                  ┌─────────────────────┐
                  │  gpt-realtime-      │  ✅ would be in use:
                  │  whisper            │      • voicemail
                  │                     │      • bilingual capture
                  │                     │      • note-taker mode
                  │                     │      • eval generation
                  │                     │      • audit transcripts
                  └─────────────────────┘
```

Each feature is additive and self-contained. None require platform
rewrites. They share the same general seam in the edge — a
`TranscriptionCompanion` class that wraps a whisper WebSocket and
plugs into the existing audio pipeline at the points where audio
is already being decoded/forwarded.

---

## Where the seams already are

If you want to start adding any of these tomorrow, the relevant
existing files are:

| Concern | File |
|---|---|
| Model selection per session | `edge/src/openai/session.ts` (`switchModel`, constructor) |
| Mode constraints in DB | `core/alembic/versions/20260507_000001_initial.py` (the `mode` CHECK) |
| Mode literals in code | `core/src/cockpit_core/agent/contract.py` (SessionContext.mode), `api/sessions.py` (CreateSessionBody.mode) |
| Edge audio fan-out | `edge/src/twilio/media-stream.ts` (the `'media'` case calls `session.appendAudio`); add `companion.appendAudio` here |
| Per-vertical config flags | `verticals/<name>/pack.yaml` + `core/src/cockpit_core/verticals/loader.py` |
| Cockpit modes UI | `frontend/src/cockpit/ModeBadge.tsx`, `ModeToggle.tsx`, `App.tsx` (route definitions) |

The seam pattern across all five features:

1. **A new mode value** (or a new vertical flag).
2. **A model id mapped to that mode** in the edge.
3. **A new transcript-handling path** that lands in `app.turns`.
4. **A cockpit affordance** to surface the new artifact.

Once one feature ships, the next four become trivial copy-paste.

---

## Where to read next

- The model in use today: [reference/gpt-realtime-2.md](gpt-realtime-2.md).
- How modes get swapped on the wire: [concepts/translate-mode.md](../concepts/translate-mode.md).
- The data store these features write into: [concepts/realtime-conversations.md](../concepts/realtime-conversations.md).
- The platform's vertical-pack mechanism that feature 5 builds on:
  [concepts/voice-agents.md](../concepts/voice-agents.md).
