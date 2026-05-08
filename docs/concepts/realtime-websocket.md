# Realtime over WebSocket — the phone bridge

> **OpenAI guide:** [Realtime WebSocket](https://developers.openai.com/api/docs/guides/realtime-websocket)
> **Where it lands:** the Twilio Media Streams handler, plus the edge's
> server-to-server connection to OpenAI.

---

## Why phones force WebSocket

A WebRTC peer connection works between a browser and a peer that can
speak ICE/STUN/TURN/DTLS-SRTP. Twilio cannot. Twilio bridges the
public phone network (PSTN) into your application by **opening a
WebSocket from Twilio's data center to your edge** and streaming the
caller's audio over it.

So the phone path is **WebSocket end to end**:

```
PSTN  →  Twilio's SIP termination  →  Twilio Media Streams (WebSocket)  →  edge

edge  →  OpenAI Realtime WebSocket  →  model
```

The WebSocket transport for OpenAI Realtime is **the only sensible
choice** when you're running server-to-server: there's no browser, no
DTLS-SRTP context, no peer ICE state to manage. Just a long-lived TCP
connection with TLS, sending JSON messages and base64 audio frames.

---

## The two WebSockets

A single inbound phone call holds two WebSockets open in the edge
process at the same time:

```
Twilio side                              OpenAI side
───────────                              ───────────
WS in  → Twilio Media Stream             WS out → wss://api.openai.com/v1/realtime
                                                  ?model=gpt-realtime-2
Frames: 8 kHz μ-law-encoded,             Frames: 24 kHz PCM-16, base64,
        20 ms each, base64                       inside JSON events
```

The edge process is the only thing that knows both. Its job is to
translate between them:

```
Twilio inbound (caller speaks):
  μ-law 8 kHz  ─decode─►  PCM-16 8 kHz  ─resample─►  PCM-16 24 kHz
                                                         │
                                                         ▼
                                            base64 + input_audio_buffer.append
                                                         │
                                                         ▼
                                                   OpenAI Realtime

OpenAI inbound (model speaks):
  response.output_audio.delta (base64 PCM-16 24 kHz)
                                                         │
                                                         ▼
  PCM-16 24 kHz  ─resample─►  PCM-16 8 kHz  ─encode─►  μ-law 8 kHz
                                                         │
                                                         ▼
                                                   Twilio Media Stream
                                                   (event: media)
```

That whole pipeline lives in `edge/src/twilio/audio.ts` (the codec)
and `edge/src/twilio/media-stream.ts` (the bridge).

---

## A primer on μ-law

μ-law (pronounced "mu-law") is a half-century-old audio compression
format defined in ITU-T G.711. It compresses 16-bit linear PCM into
8 bits per sample using a non-linear quantization curve — small
amplitudes get fine resolution, large amplitudes get coarser.

For speech (which has a roughly logarithmic dynamic range), the
perceived quality difference vs. linear PCM is small. For 8 kHz
sample rate × 8 bits = 64 kbit/s, which is exactly the bandwidth of
a single PSTN voice channel.

Why this matters here: Twilio's Media Streams send μ-law frames. To
get back to a linear-PCM signal that OpenAI can process, the edge has
to **decode** every byte to the corresponding 16-bit sample. The
implementation in `edge/src/twilio/audio.ts` is straight from the
G.711 reference tables — no external library — about 30 lines of
TypeScript.

```ts
export function muLawDecodeByte(byte: number): number {
  byte = ~byte & 0xff;
  const sign = byte & 0x80;
  const exponent = (byte >> 4) & 0x07;
  const mantissa = byte & 0x0f;
  let sample = ((mantissa << 3) + 0x84) << exponent;
  sample -= 0x84;
  return sign ? -sample : sample;
}
```

The encoder is the inverse, used on the way back out to Twilio.

---

## Sample-rate conversion (resampling)

Twilio: 8 kHz. OpenAI: 24 kHz. So every inbound frame triples in
length, and every outbound frame thirds.

The implementation is **linear interpolation**:

```ts
export function resamplePcm16(input: Int16Array, fromHz: number, toHz: number): Int16Array {
  if (fromHz === toHz) return input;
  const ratio = fromHz / toHz;
  const outLen = Math.floor(input.length / ratio);
  const out = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const src = i * ratio;
    const lo = Math.floor(src);
    const hi = Math.min(lo + 1, input.length - 1);
    const frac = src - lo;
    out[i] = Math.round(input[lo] * (1 - frac) + input[hi] * frac);
  }
  return out;
}
```

For high-quality music you'd use a polyphase filter or a windowed
sinc. For phone-band speech (which is already low-pass-filtered to
3.4 kHz at the carrier) linear interpolation is indistinguishable.
The cost-benefit doesn't justify a heavier implementation.

---

## The Twilio Media Stream WebSocket protocol

Twilio's WebSocket protocol carries five message types:

| Event | Direction | Meaning |
|---|---|---|
| `connected` | Twilio → us | WS handshake complete |
| `start` | Twilio → us | Call started; carries `streamSid`, `callSid`, custom params |
| `media` | both | A 20 ms frame of base64 μ-law audio |
| `mark` | both | Optional sync marker |
| `stop` | Twilio → us | Call ended |

The `start` event payload includes `customParameters` — any `<Parameter>`
elements you put inside the TwiML `<Stream>` are surfaced here. We use
this to pass `vertical=hvac` from the webhook into the media-stream
handler:

```xml
<Response>
  <Connect>
    <Stream url="wss://example.com/twilio/media-stream">
      <Parameter name="vertical" value="hvac"/>
    </Stream>
  </Connect>
</Response>
```

To send audio back to Twilio, we emit:

```json
{
  "event": "media",
  "streamSid": "MZ...",
  "media": { "payload": "<base64 μ-law>" }
}
```

Twilio buffers and plays these frames to the caller. There's no
heartbeat or keepalive; if no media flows for ~30 s Twilio assumes
the call is dead.

---

## The OpenAI Realtime WebSocket protocol (GA)

The edge opens this WebSocket per call:

```
URL: wss://api.openai.com/v1/realtime?model=gpt-realtime-2
Headers:
  Authorization: Bearer <OPENAI_API_KEY>
```

Note: in the **GA** API, **the `OpenAI-Beta: realtime=v1` header is
gone**. Sending it will not break anything, but it's not required.

After the WS opens, send `session.update` to configure the session:

```json
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "model": "gpt-realtime-2",
    "instructions": "You are Aria, the dispatcher for an HVAC company. ...",
    "output_modalities": ["audio"],
    "tools": [
      { "type": "function", "name": "parts_lookup", "description": "...",
        "parameters": { "type": "object", "properties": {...}, "required": [] } },
      ...
    ],
    "audio": {
      "input": {
        "format": { "type": "audio/pcm", "rate": 24000 },
        "turn_detection": { "type": "semantic_vad" },
        "transcription": { "model": "whisper-1" }
      },
      "output": {
        "format": { "type": "audio/pcm", "rate": 24000 },
        "voice": "alloy"
      }
    }
  }
}
```

This is the GA shape, which differs from the beta in three big ways:

| Field | Beta | GA |
|---|---|---|
| `session.type` | not required | required, must be `"realtime"` |
| `modalities` | array at top level | renamed to `output_modalities` |
| `voice` | top level | nested under `audio.output.voice` |
| `turn_detection` | top level | nested under `audio.input.turn_detection` |
| `input_audio_transcription` | top level | renamed to `audio.input.transcription` |

The migration is captured in `edge/src/openai/session.ts` —
specifically in the `ws.on('open', ...)` handler.

---

## The events flow

Once `session.update` is sent, the WebSocket carries these events
back and forth:

### Client → server

| Event | Purpose |
|---|---|
| `session.update` | Configure the session (instructions, tools, voice, …) |
| `input_audio_buffer.append` | Append a base64 PCM-24kHz frame |
| `input_audio_buffer.commit` | Force end-of-utterance (server VAD usually handles this) |
| `response.create` | Ask the model to produce a response now |
| `conversation.item.create` (with `type: function_call_output`) | Reply to a tool call |

### Server → client

| Event | Purpose |
|---|---|
| `session.created` | Sent right after the WS opens |
| `input_audio_buffer.speech_started` / `.speech_stopped` | VAD lifecycle |
| `response.output_audio.delta` | Base64 PCM-24kHz audio frame from the model |
| `response.output_audio_transcript.delta` | Streaming text of the model's spoken response |
| `response.done` | Response complete — the `output[]` array contains both `message` items and `function_call` items |
| `error` | Something went wrong (auth, schema, rate limit, …) |

Note the GA renames here too: `response.audio.delta` →
`response.output_audio.delta`, `response.audio_transcript.delta` →
`response.output_audio_transcript.delta`. Function calls used to
arrive as their own event (`response.function_call_arguments.done`)
in the beta; in GA they're embedded in `response.done.output[]`.

---

## Function calls over the WebSocket

When the model decides to call a tool, the relevant chunk of
`response.done` looks like:

```json
{
  "type": "response.done",
  "response": {
    "id": "resp_...",
    "output": [
      {
        "type": "function_call",
        "name": "parts_lookup",
        "call_id": "call_<id>",
        "arguments": "{\"part_description\":\"capacitor\",\"model_number\":\"Carrier-58STA\"}"
      }
    ]
  }
}
```

The edge sees `output[].type === "function_call"`, calls the core's
`POST /v1/sessions/{id}/tool-calls` over HTTP, then sends the result
back to OpenAI as:

```json
{
  "type": "conversation.item.create",
  "item": {
    "type": "function_call_output",
    "call_id": "call_<id>",
    "output": "{\"matches\":[{\"part_number\":\"P-CAP-440-A\",...}],\"total_matches\":2}"
  }
}
```

Followed immediately by:

```json
{ "type": "response.create" }
```

The model continues, incorporating the tool result, and emits more
audio. From the caller's perspective: a brief "let me pull up that
part" preamble, then the answer. ~1.5 s end-to-end p50 on a typical
network.

---

## Reconnection and resilience

What happens if the OpenAI WebSocket drops mid-call?

v1 does the simple thing: it surfaces the close to the surface (the
caller hears silence), the call eventually ends, the conversation row
is finalized with whatever state was persisted up to that point.

Future iterations will:

1. Buffer the most recent N seconds of audio in Redis (the spec
   reserves room for this).
2. On disconnect, re-open a new OpenAI WebSocket with a *resume*
   pattern that reconstructs the conversation context from
   `app.turns`.
3. Reinject buffered audio so the caller doesn't notice.

The seam for this is the `RealtimeSession` class: today it's a thin
wrapper around one WS; tomorrow it gains a state machine.

---

## Why not WebRTC for the phone path?

Even if Twilio supported WebRTC end-to-end (it does for some
products), bridging WebRTC ↔ PSTN requires SIP gateways anyway. So:

| If your call source is | Use |
|---|---|
| A browser | WebRTC end-to-end (or our v1 WebSocket+PCM compromise) |
| A phone (PSTN/VoIP) | Telephony provider → WebSocket → server (Twilio Media Streams is the gold-standard implementation) |
| A meeting bot | WebSocket from the meeting tab to your server |

WebSocket-to-server is the universal bridge. WebRTC's value comes
from peer-to-peer optimization that doesn't apply when one peer is
already a server in OpenAI's data center.

---

## Where to read next

- The Twilio side, end-to-end: [reference/twilio-integration.md](../reference/twilio-integration.md).
- The model on the other end: [reference/gpt-realtime-2.md](../reference/gpt-realtime-2.md).
- How tool calls actually get dispatched: [running-agents.md](running-agents.md).
