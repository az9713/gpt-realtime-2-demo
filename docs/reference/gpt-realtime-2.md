# gpt-realtime-2 — the model behind the cockpit

A complete reference for the model this app revolves around: what it
is, what it accepts, what it emits, and how the GA shape differs from
the older beta.

---

## What it is

`gpt-realtime-2` is OpenAI's production-grade real-time
**speech-to-speech** model, launched in late 2026. It's the GA
successor to `gpt-4o-realtime-preview` (the late-2024/early-2025 beta
that pioneered the WebSocket-based real-time API).

Key properties:

- **End-to-end audio.** You stream audio in; the model generates audio
  out — same neural network handling both. There's no separate ASR
  (speech-to-text) → LLM → TTS pipeline.
- **Mid-stream tool calling.** While the model is mid-thought, it can
  emit `function_call` items asking your application to run something
  and feed the result back.
- **Bidirectional, full-duplex.** The user can interrupt the model
  mid-response. Server VAD detects speech onset and the model gracefully
  yields.
- **Multiple voices.** Configurable per session via
  `audio.output.voice`.
- **Multiple modalities.** Output can be audio + text, or text-only.

It's accessed via a single WebSocket connection. No separate signaling
server, no peer connection state, no chunked HTTP streaming.

---

## Endpoint

```
wss://api.openai.com/v1/realtime?model=gpt-realtime-2
```

Required headers:

| Header | Value | Notes |
|---|---|---|
| `Authorization` | `Bearer <OPENAI_API_KEY>` | Standard OpenAI auth |

That's it. **In particular, `OpenAI-Beta: realtime=v1` is no longer
required for GA models.** Sending it is harmless but unnecessary.

The optional `OpenAI-Safety-Identifier` header takes a hashed user
identifier and helps OpenAI's abuse-monitoring systems handle
different end-users separately. Recommended for production but not
required.

---

## Companion models

| Model | Purpose | Endpoint |
|---|---|---|
| `gpt-realtime-2` | Conversational default; reasons, calls tools | `wss://api.openai.com/v1/realtime?model=gpt-realtime-2` |
| `gpt-realtime-translate` | Passthrough translator; no tools, no reasoning | `wss://api.openai.com/v1/realtime?model=gpt-realtime-translate` |
| `gpt-realtime-whisper` | Streaming transcription only; no audio output, no reasoning | `wss://api.openai.com/v1/realtime?intent=transcription` (no `model=` query — model goes in `audio.input.transcription.model`) |

Switching between `gpt-realtime-2` and `gpt-realtime-translate` is a
tear-down + re-open of the WebSocket — same URL family, just a
different `model=` value. This codebase's mode switcher does exactly
that. See [translate-mode.md](../concepts/translate-mode.md).

`gpt-realtime-whisper` lives at a **separate URL** (the
`?intent=transcription` endpoint) — connecting to it as if it were a
regular realtime session returns *"Passing a transcription session
update event to a realtime session is not allowed."* The
codebase has a dedicated `TranscriptionSession` class that uses the
correct URL; see
[realtime-models-in-use.md](realtime-models-in-use.md#3-gpt-realtime-whisper--the-transcription-specialist).

---

## The session vs the conversation

When you open the WebSocket, OpenAI assigns a **session**. The session
holds:

- Your `instructions` (the system prompt).
- Your `tools` (the tool registry).
- Audio config (voice, format, turn detection, transcription).
- A rolling **conversation buffer** — every user/assistant/tool item
  the session has produced.

The session lives until the WebSocket closes. The conversation buffer
is *not* persisted by OpenAI — it's reset every time you reconnect.

This codebase's `app.conversations` is a *different concept*: it's our
durable record across sessions. See
[realtime-conversations.md](../concepts/realtime-conversations.md).

---

## The session.update event (GA shape)

After the WebSocket opens, send exactly one `session.update` event to
configure the session. The GA-shape payload:

```json
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "model": "gpt-realtime-2",
    "instructions": "You are Aria, the dispatcher for an HVAC company. ...",
    "output_modalities": ["audio"],
    "tools": [
      {
        "type": "function",
        "name": "parts_lookup",
        "description": "Look up parts by model number and/or description.",
        "parameters": {
          "type": "object",
          "properties": {
            "model_number":     { "type": "string" },
            "part_description": { "type": "string" }
          },
          "required": []
        }
      }
    ],
    "audio": {
      "input": {
        "format":          { "type": "audio/pcm", "rate": 24000 },
        "turn_detection":  { "type": "semantic_vad" },
        "transcription":   { "model": "whisper-1" }
      },
      "output": {
        "format": { "type": "audio/pcm", "rate": 24000 },
        "voice":  "alloy"
      }
    }
  }
}
```

### Required fields

- `session.type` — must be `"realtime"`. **This is the field that
  was missing in our first build attempt and produced the error
  `Missing required parameter: 'session.type'`.**
- `session.model` — the model id. Strictly speaking the WebSocket URL
  already pinned the model, but supplying it here is required for the
  `session.update` validator.

### Optional fields

- `instructions` — the system prompt. Can be re-sent at any time
  during the session to change behavior mid-conversation.
- `output_modalities` — array of `"text"` and/or `"audio"`. Default is
  both; setting `["text"]` silences spoken output (useful for
  meeting-overlay or note-taker scenarios).
- `tools` — function-tool descriptors. See "Tools" below.
- `audio.input.format` — typically `{ "type": "audio/pcm", "rate": 24000 }`.
- `audio.input.turn_detection` — `{ "type": "semantic_vad" }` is the
  GA default and a major upgrade over `server_vad`. Set to `null` to
  disable server-side VAD entirely.
- `audio.input.transcription` — set to `{ "model": "whisper-1" }` (or
  `{ "model": "gpt-4o-transcribe" }` if you want OpenAI's newer ASR).
  Without this, you don't get user-transcript events.
- `audio.output.voice` — currently one of: `alloy`, `ash`, `ballad`,
  `coral`, `echo`, `marin`, `sage`, `shimmer`, `verse`, …
- `audio.output.format` — `{ "type": "audio/pcm", "rate": 24000 }`.

### Differences from the beta

If you're porting from `gpt-4o-realtime-preview`, here's the diff:

| Beta | GA | Notes |
|---|---|---|
| (no field) | `session.type: "realtime"` | New required field |
| `modalities: ["text", "audio"]` | `output_modalities: ["audio"]` | Renamed; restricted to output channels |
| `voice: "alloy"` | `audio.output.voice: "alloy"` | Moved into audio.output |
| `turn_detection: { "type": "server_vad" }` | `audio.input.turn_detection: { "type": "semantic_vad" }` | Moved + new default type |
| `input_audio_transcription: { "model": "whisper-1" }` | `audio.input.transcription: { "model": "whisper-1" }` | Renamed + moved |

---

## Tools

A tool is a function the model can choose to call. Each tool is
specified at session-update time as:

```json
{
  "type": "function",
  "name": "parts_lookup",
  "description": "Look up parts by model number and/or description.",
  "parameters": {
    "type": "object",
    "properties": { ... },
    "required": [ ... ]
  }
}
```

Three things matter:

1. **`name`** must be a valid identifier. The model uses this to
   refer to the tool in `function_call` items.
2. **`description`** is the model's primary signal for *when* to call
   the tool. Write it like a usage hint, not an implementation note.
3. **`parameters`** is a JSON Schema. The model will produce arguments
   that conform to it (mostly — schemas are a hint, not a strict
   constraint, and the model occasionally emits extra fields).

A model session can have up to ~20 tools without notable degradation.
Beyond that you start seeing the model pick wrong tools more often;
consider sub-agent routing.

---

## Client → server events

After `session.update`, the events you send most often:

| Event | Payload | Purpose |
|---|---|---|
| `input_audio_buffer.append` | `{ "audio": "<base64>" }` | Append a base64 PCM-24 frame |
| `input_audio_buffer.commit` | `{}` | Force end-of-input (server VAD usually handles this) |
| `response.create` | `{}` | Ask the model to respond now |
| `conversation.item.create` (with `item.type: "function_call_output"`) | `{ "item": { "type": "function_call_output", "call_id": "...", "output": "<json>" } }` | Reply to a tool call |
| `session.update` | (full session config) | Re-configure mid-session |
| `session.update` (partial) | `{ "session": { "instructions": "..." } }` | Mutate just one field |

You can also send `conversation.item.create` with type `"message"` to
inject text into the conversation as if the user had said it. Useful
for cockpit-side prompts ("the dispatcher just resolved your approval —
proceed.").

---

## Server → client events

The events you'll see most often in `gpt-realtime-2` GA:

### Session lifecycle

| Event | Meaning |
|---|---|
| `session.created` | The WS just opened; session is configured with defaults |
| `session.updated` | A `session.update` you sent was accepted |
| `error` | Something went wrong; payload has `error.code`, `error.message` |

### Audio in (user)

| Event | Meaning |
|---|---|
| `input_audio_buffer.speech_started` | Server VAD detected user speech onset |
| `input_audio_buffer.speech_stopped` | Server VAD detected user end-of-utterance |
| `input_audio_buffer.committed` | Buffer was committed (auto via VAD or via your `commit` event) |
| `conversation.item.input_audio_transcription.completed` | User's audio was transcribed (because `audio.input.transcription` was set) |

### Audio out (model)

| Event | Meaning |
|---|---|
| `response.output_audio.delta` | Base64 PCM-24 audio chunk from the model |
| `response.output_audio.done` | Audio response complete |
| `response.output_audio_transcript.delta` | Streaming text of the model's spoken response |
| `response.output_audio_transcript.done` | Transcript of agent response complete |
| `response.done` | Response complete; output[] has every item produced |

### Function calling

In GA, function calls arrive **embedded in `response.done`**:

```json
{
  "type": "response.done",
  "response": {
    "id": "resp_...",
    "output": [
      { "type": "message", ... },
      {
        "type": "function_call",
        "name": "parts_lookup",
        "call_id": "call_...",
        "arguments": "{\"part_description\":\"capacitor\"}"
      }
    ],
    "usage": { ... }
  }
}
```

Walk `output[]`, find `type === "function_call"`, dispatch each. Reply
with one `function_call_output` per call, then `response.create` to
resume.

(In the beta, function calls had their own dedicated event,
`response.function_call_arguments.done`. Code that handled both — like
this codebase, in `edge/src/openai/session.ts` — works against both
APIs because the GA-style `response.done.output[]` walk covers GA and
the explicit beta event handler is still there as a fallback.)

---

## Audio format

OpenAI Realtime expects **PCM-16, 24 kHz, mono, little-endian**, sent
as base64 strings inside `input_audio_buffer.append` events.

That works out to:

- 24 000 samples / second
- 2 bytes per sample
- = 48 000 bytes / second of raw audio
- ≈ 65 000 bytes / second of base64

Frame size is up to you. Common choices:

- **20 ms (480 samples = 960 bytes raw)** — matches Twilio's frame
  size. Lowest latency.
- **100 ms (2400 samples)** — fewer events, higher latency. Good for
  bandwidth-constrained scenarios.

This codebase uses 20 ms frames for the Twilio path (it's what Twilio
sends) and ~85 ms frames for the browser path (the
`ScriptProcessor`'s 4096-sample buffer at 24 kHz = 4096/24000 ≈ 170 ms;
we trigger commits every ~250 ms regardless).

The output audio format is the same: 24 kHz PCM-16, mono, little-endian
base64 inside `response.output_audio.delta` events. Decode and play
to the user's surface.

---

## Latency budget

A typical conversation turn:

| Step | Latency contribution |
|---|---|
| User speaks; VAD detects end | 300-700 ms (semantic_vad is fast) |
| Model decides + tool calls | 200-500 ms |
| Tool execution (your code) | 50-500 ms |
| Model resumes generation | 100 ms |
| First audio frame arrives | already streaming |
| Audio reaches user | network round-trip |

End-to-end p50 for a one-tool turn on a local network: ~1.5 s.

Things that blow the budget:

- Tool registry > 20 tools — model attention slips, bad tool calls,
  retries.
- Long instructions (>2000 tokens) — model has to read more on every
  turn.
- Slow tool handler — the spec's checkpoint is "halt feature work and
  optimize" if p50 > 1.5 s. Use trace events to identify the slow
  step.

---

## Pricing (approximate, 2026 GA)

Pricing changes; check OpenAI's current dashboard. Approximate at GA:

| Token type | Approx price |
|---|---|
| Input audio | $32 / 1M tokens |
| Cached input audio | $0.40 / 1M tokens |
| Output audio | $64 / 1M tokens |
| Input text | $4 / 1M tokens |
| Output text | $16 / 1M tokens |

A 5-minute conversation with moderate tool use roughly costs $0.30-$0.50.

Translate mode (`gpt-realtime-translate`) is priced similarly per
token but produces fewer total tokens since it's not reasoning,
just relaying.

---

## Limits

| Property | Limit |
|---|---|
| Concurrent sessions | Per OpenAI org tier; check your dashboard |
| Session duration | Up to 30 minutes per WebSocket; reconnect on drop |
| Tool count per session | Soft limit at ~20 before quality drops |
| Instructions length | Practical max ~4000 tokens |
| Audio frame size | 20 ms minimum, no hard max (but very large frames hurt latency) |

---

## Errors you'll actually see

In our first build attempt we hit two of these. They're both
documented now in the source:

| Error | Cause |
|---|---|
| `invalid_model: Model "X" is only available on the GA API.` | You're using the beta path (`OpenAI-Beta` header). Drop the header. |
| `missing_required_parameter: 'session.type'` | Beta-shape session.update sent against GA model. Add `session.type: "realtime"`. |
| `unknown_parameter: 'modalities'` | You're using beta-shape `modalities`. Rename to `output_modalities`. |
| `invalid_value: turn_detection.type` | Beta value `"server_vad"` against GA. Use `"semantic_vad"` (or it's now nested under `audio.input.turn_detection`). |
| `rate_limit_exceeded` | You hit your concurrent-session cap. Tier up or queue. |

---

## Where to read next

- How this codebase wires up the WebSocket: [realtime-websocket.md](../concepts/realtime-websocket.md).
- The browser path (uses the same model, different transport):
  [realtime-webrtc.md](../concepts/realtime-webrtc.md).
- The cockpit's mode switching: [translate-mode.md](../concepts/translate-mode.md).
- OpenAI's official model docs: <https://developers.openai.com/api/docs/guides/realtime>
