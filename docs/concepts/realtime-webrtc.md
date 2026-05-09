# Realtime over WebRTC — the browser surface

> **OpenAI guide:** [Realtime WebRTC](https://developers.openai.com/api/docs/guides/realtime-webrtc)
> **Where it lands:** the browser cockpit (and a future meeting overlay).

---

## The job

Get audio out of the operator's microphone, into the OpenAI Realtime
model, and the model's response audio back out of the operator's
speakers — with low enough latency that the conversation feels natural.

"Low enough" means roughly **150 ms one-way** or under. Beyond that,
people start talking over the model.

---

## Two ways to do this

The OpenAI Realtime API supports two transports:

| Transport | What it is | When to use |
|---|---|---|
| **WebRTC** | Browser-native peer connection over UDP, with DTLS-SRTP encryption | Browsers, where you want minimum latency and resilience to packet loss |
| **WebSocket** | TCP-based message stream | Servers (like our edge), or simpler clients where TCP head-of-line blocking is acceptable |

This doc is about the WebRTC path (browser side). For the WebSocket
path see [realtime-websocket.md](realtime-websocket.md).

---

## What is WebRTC anyway?

WebRTC is a browser standard for **real-time peer-to-peer media**. It
was designed for video calls (Google Meet, Discord) and has three
big pieces:

1. **Signaling** — how two peers exchange "I want to call you" and
   "here's how to find me." Not part of WebRTC itself; you bring your
   own (typically a WebSocket on a regular server).
2. **ICE / STUN / TURN** — protocols for figuring out a network path
   between two peers through firewalls and NATs. Your browser tries
   direct, then via a STUN server (which tells you your public IP),
   then via a TURN relay if direct paths fail.
3. **DTLS-SRTP** — encrypted UDP carrying audio and video frames once
   the ICE handshake is done.

The result, when it works, is a direct UDP connection between the two
peers with end-to-end encryption and very low latency.

---

## How OpenAI's WebRTC mode works

OpenAI provides a **signaling endpoint** at
`https://api.openai.com/v1/realtime/calls`. The flow is:

```
1. Browser asks for mic permission, captures audio.
2. Browser creates an RTCPeerConnection, attaches the mic track.
3. Browser generates an SDP offer.
4. Browser POSTs the offer to the signaling endpoint with
   Authorization: Bearer ${ephemeral_token}.
5. OpenAI returns an SDP answer.
6. Browser sets the remote description.
7. ICE finishes, DTLS-SRTP starts, audio flows directly between
   browser and OpenAI.

In parallel:
8. Browser opens an RTCDataChannel (also part of the peer connection).
9. The same session.update / tool / response events flow over this
   channel — same vocabulary as the WebSocket transport.
```

The catch: the browser holds an `Authorization: Bearer` token to
authenticate the signaling POST. You don't want to expose your
real OpenAI API key to the browser. Instead you mint a short-lived
**ephemeral token** server-side and hand it to the browser. The
ephemeral token is scoped to one session.

---

## What v1 of this app actually does

**v1 does not use WebRTC.** It uses a simpler approach: the browser
opens a single WebSocket to our edge, and we ferry base64-encoded PCM
frames through it. The edge then opens a *second* WebSocket
(server-to-server) to OpenAI Realtime.

```
┌──────────────────┐                ┌──────────────────┐
│  browser cockpit │                │  edge (Node)     │
│  ──────────────  │                │  ──────────────  │
│                  │   WebSocket    │                  │   WebSocket
│  getUserMedia    │ ←─── PCM ────→ │  bridge          │ ←──→ OpenAI
│  ScriptProcessor │   base64       │                  │
│  AudioContext    │                │                  │
└──────────────────┘                └──────────────────┘
        ↑                                     ↑
        └─── on the user's laptop ────────────┘
```

This was a deliberate v1 simplification, captured in the spec:

> v1 browser audio runs over the same WebSocket as control via base64
> PCM frames; full WebRTC with DTLS-SRTP is reserved for a future
> iteration.
>
> — `edge/src/webrtc/peer.ts` comment

The reasons:

| Concern | WebRTC | WebSocket-PCM (v1) |
|---|---|---|
| Latency on a good network | Best | Good (TCP head-of-line blocking is rare on a LAN) |
| Latency on a lossy network | Best (UDP recovers fast) | Worse (TCP retransmits) |
| Browser audio capture API | `getUserMedia` + `RTCPeerConnection` | `getUserMedia` + `AudioContext` + `ScriptProcessor` |
| Server-side complexity | Need ICE/STUN/TURN handshake mediator | Just a WebSocket route |
| Code volume | ~500 lines of signaling/peer code | ~200 lines of bridge code |
| Works through corporate firewalls? | Sometimes (UDP is often blocked) | Yes (TCP 443 always works) |
| End-to-end encryption | DTLS-SRTP per peer | TLS to edge; edge re-encrypts to OpenAI |

For an operator-facing cockpit on a local network where the dispatcher
is sitting next to their laptop, the WebSocket-PCM approach is fine.
For a future meeting bot scenario where audio quality and packet-loss
resilience matter more, true WebRTC is the right answer.

The seam is in place: `edge/src/webrtc/peer.ts` exports a stub
`PeerConnectionBridge` interface that documents the eventual shape.

---

## How the v1 browser path works, step by step

### Browser side (`frontend/src/cockpit/TalkPage.tsx`)

```ts
// 1. Open a WebSocket directly to the edge.
const wsUrl = `${VITE_EDGE_URL.replace(/^http/, 'ws')}/v1/voice/browser?vertical=hvac`;
const ws = new WebSocket(wsUrl);

// 2. When the edge confirms session.created, capture the mic.
ws.onopen = async () => {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const ctx = new AudioContext({ sampleRate: 24_000 }); // OpenAI's rate
  const source = ctx.createMediaStreamSource(stream);
  const processor = ctx.createScriptProcessor(4096, 1, 1);
  source.connect(processor);
  processor.connect(ctx.destination);

  // 3. Every audio buffer becomes a base64 PCM frame.
  processor.onaudioprocess = (event) => {
    const float32 = event.inputBuffer.getChannelData(0);
    const pcm16 = floatToInt16(float32);
    const b64 = btoa(String.fromCharCode(...new Uint8Array(pcm16.buffer)));
    ws.send(JSON.stringify({ kind: 'audio.append', audio: b64 }));
  };
};

// 4. Inbound: agent audio comes back as audio.delta messages.
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.kind === 'audio.delta') enqueueAgentAudio(msg.audio);
  if (msg.kind === 'transcript.delta') append({ role: 'agent', text: msg.text, partial: true });
  // ...
};
```

The audio plays through a second `AudioContext` configured for 24 kHz
output. We decode each base64 frame into Int16Array, build an
`AudioBuffer`, and schedule it at `playbackTimeRef.current` so frames
play sequentially without gaps.

### Edge side (`edge/src/webrtc/signaling.ts`)

```ts
app.get('/v1/voice/browser', { websocket: true }, async (socket, request) => {
  // 1. Tell the core a new session is starting.
  const config = await coreClient.createSession({ surface: 'browser', vertical: 'hvac' });
  // 2. Open the OpenAI Realtime WebSocket.
  const session = new RealtimeSession(settings, coreClient, config, {
    onAudioDelta: (b64) => socket.send(JSON.stringify({ kind: 'audio.delta', audio: b64 })),
    onTranscriptDelta: (delta) => socket.send(JSON.stringify({ kind: 'transcript.delta', text: delta })),
    // ...
  });
  await session.open();
  socket.send(JSON.stringify({ kind: 'session.created', conversation_id: config.conversation_id, ... }));

  // 3. Forward inbound audio frames to OpenAI.
  socket.on('message', (raw) => {
    const msg = JSON.parse(raw.toString());
    if (msg.kind === 'audio.append') session.appendAudio(msg.audio);
    if (msg.kind === 'audio.commit') session.commitInput();
  });

  // 4. On close, tear down both sides.
  socket.on('close', () => {
    session.close();
    coreClient.endSession(config.conversation_id);
  });
});
```

That's the whole v1 browser path: ~80 lines of TypeScript, no peer
connection state machine, no STUN/TURN configuration.

---

## Why a single AudioContext at 24 kHz, not two?

The browser side has *two* AudioContexts:

- **Capture context** at 24 kHz, used by `getUserMedia` to read mic samples.
- **Playback context** at 24 kHz, used to schedule agent audio frames.

We use 24 kHz on both ends so we never have to resample on the
browser. The OpenAI Realtime model emits PCM-24kHz audio; the model
expects PCM-24kHz audio in. Browsers happily set up an AudioContext at
that rate. (The phone path resamples 8 kHz ↔ 24 kHz because Twilio
forces 8 kHz μ-law on the wire.)

---

## Voice activity detection (VAD): who decides when the user has stopped?

Two choices:

| Approach | Who decides | Pros | Cons |
|---|---|---|---|
| **Client VAD** | Browser pushes `input_audio_buffer.commit` when it detects silence | Lower OpenAI cost (you control buffering) | You have to build VAD; fragile across mics |
| **Server VAD** | OpenAI decides via `turn_detection` | Robust, well-tuned | The model commits the buffer for you |

v1 uses **server VAD** with the GA-default `semantic_vad` setting.
That's set in `session.update` from the edge:

```ts
audio: {
  input: {
    format: { type: 'audio/pcm', rate: 24_000 },
    turn_detection: { type: 'semantic_vad' },
    transcription: { model: 'whisper-1' },
  },
  output: { format: { type: 'audio/pcm', rate: 24_000 }, voice: 'alloy' },
}
```

The browser does **not** push manual
`input_audio_buffer.commit` frames. With `semantic_vad` the model
auto-commits and auto-creates responses; an extra client-side timer
races with VAD and double-fires `response.create` while a previous
response is still generating, which manifests as the agent looping
the same fragment over and over. (See the "Agent cannot stop talking"
runbook entry in [`ops.md`](../ops.md) for the postmortem.) The edge
*does* still accept `audio.commit` messages from clients that opt in
— the Twilio media-stream path uses one — but the browser cockpit
doesn't.

---

## Echo cancellation, noise suppression, AGC

These are the three classic problems with any voice agent:

- **Echo** — the model's own audio coming back into the mic. With
  speakers + mic on the same laptop this would loop into a feedback
  spiral.
- **Background noise** — keyboard clacks, kids in the next room.
- **Automatic gain** — the user too quiet or too loud.

The `getUserMedia` constraints in v1 are minimal (`{ audio: true }`),
which gets you the browser's defaults. Modern Chrome already applies:

- WebRTC echo cancellation (only when output is the system speakers).
- Noise suppression.
- Automatic gain control.

For a cockpit deployment where the operator wears a headset, that's
plenty.

### Half-duplex gate as a second line of defense

Browser AEC is imperfect: across two separate `AudioContext`s (one
for capture, one for playback), and on lossy laptop speakers, enough
agent audio leaks back into the mic to push `semantic_vad` over its
turn-end threshold — **without** producing a meaningful user
transcript. The result is an agent that auto-generates response after
response on top of empty/echo input.

So `processor.onaudioprocess` in `TalkPage.tsx` has a half-duplex
gate:

```ts
processor.onaudioprocess = (event) => {
  if (ws.readyState !== ws.OPEN) return;
  // Half-duplex: while agent audio is queued for playback, drop mic frames.
  const playerCtx = playerCtxRef.current;
  if (playerCtx && playbackTimeRef.current > playerCtx.currentTime + 0.05) {
    return;
  }
  // ...encode and send the mic frame
};
```

While the agent is speaking, mic frames are dropped on the floor. The
trade-off: the user can't barge-in mid-utterance. For an operator
console where the dispatcher is mostly listening to the agent and
acting between turns, that's the right call. Removing the gate
requires either headphones (no acoustic echo) or proper AEC across
the two AudioContexts.

For a meeting overlay where you need to capture multiple people's
audio at once, you'd pass richer constraints
(`echoCancellation: true, noiseSuppression: true, channelCount: 1`)
and consider WebRTC's audio processing module directly.

---

## The "meeting overlay" future state

The same browser audio path described here scales to capture *any*
audio source the browser can reach:

- A meeting tab via `getDisplayMedia({ audio: true })` (Chrome only,
  with user consent).
- An OS-level virtual cable via `getUserMedia({ audio: { deviceId: 'BlackHole' } })`.

Once the audio is in `processor.onaudioprocess`, the rest of the path
is identical. Translate mode (see [translate-mode.md](translate-mode.md))
exists exactly to make this scenario useful: dispatcher attends a
Spanish-speaking customer call, and the meeting bot translates in real
time.

---

## Mental model: the browser is just one more "phone"

The single most important framing for this codebase is:

> The browser and the phone are the *same surface to the agent core*.
> They differ only in audio format (PCM-24 vs μ-law-8) and protocol
> framing (WebSocket-with-base64-PCM vs Twilio Media Streams).

That's why the agent core has zero per-surface code. The edge owns
all the surface-specific quirks; the core just sees `surface=browser`
or `surface=phone` as an annotation on each conversation row.
