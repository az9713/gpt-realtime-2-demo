# Twilio Integration — how phone calls reach the agent

A complete walkthrough of how a real phone call from a real homeowner
reaches Aria. Every step, every protocol, every config knob.

---

## What Twilio is, in one paragraph

Twilio is a cloud telephony provider. They've already built the hard
parts of telephony — interconnects with the public phone network
(PSTN), SIP termination, voice codecs, billing, regulatory
compliance — and they expose what's left as APIs and webhooks. You
buy phone numbers from Twilio, write a small XML document called
TwiML to tell Twilio what to do with calls, and Twilio handles
everything else.

For voice agents, the magic feature is **Programmable Voice + Media
Streams**: when a call comes in, Twilio can stream the raw audio
bidirectionally to your server over a WebSocket. That's how this
codebase plugs into the phone network.

---

## The three Twilio concepts you need to know

### 1. Phone numbers

You buy or port a phone number into your Twilio account. Each number
has a "voice configuration" you control via the Twilio Console or the
Twilio API. The configuration says: *when a call arrives at this
number, do this.*

For our cockpit: configure a webhook URL. When a call rings, Twilio
will POST to that URL.

### 2. TwiML — Twilio Markup Language

TwiML is a small XML dialect Twilio interprets as instructions for a
call. Think of it as a tiny, special-purpose programming language for
voice.

A TwiML document might say "play this prompt, record the response,
send it to my server." Or "connect this call to a SIP endpoint." Or,
in our case, "open a media stream to my server." Twilio reads the XML
your server returns and acts on it.

Example TwiML this codebase emits:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://example.com/twilio/media-stream">
      <Parameter name="vertical" value="hvac"/>
    </Stream>
  </Connect>
</Response>
```

This says: "open a bidirectional WebSocket from your data center to
`wss://example.com/twilio/media-stream`, send the caller's audio over
it, and play whatever audio I send back to the caller. Pass
`vertical=hvac` as a parameter so the server knows what to do."

### 3. Media Streams

Media Streams is the actual audio plane. Twilio opens a WebSocket
from their data center to your server. The protocol carries five
event types (see [realtime-websocket.md](../concepts/realtime-websocket.md))
and base64-encoded μ-law audio frames at 8 kHz.

That WebSocket is what the edge in this codebase listens on at
`/twilio/media-stream`.

---

## The end-to-end flow

```
1. Homeowner dials  +1 512-555-0150
   ────────────────────────────────────────────────────────────

   [PSTN] → SS7 routing → Twilio's SIP termination

2. Twilio recognizes "+1 512-555-0150" as your number,
   reads its voice config, finds the webhook URL:
       POST https://example.com/twilio/voice
   Twilio POSTs that URL with form data:
       Called   = +15125550150
       From     = +12145559876   (the homeowner)
       CallSid  = CA1234567...
   ────────────────────────────────────────────────────────────

3. Your edge service handles the POST:
   ────────────────────────────────────────────────────────────

   POST /twilio/voice
   ↓
   - Validates the X-Twilio-Signature header against
     TWILIO_AUTH_TOKEN. If the signature is invalid, 403.
   - Looks up the called number in PHONE_VERTICAL_MAP env var
     to find the right vertical (e.g. "hvac").
   - Returns TwiML:
       <Connect><Stream url="wss://example.com/twilio/media-stream">
         <Parameter name="vertical" value="hvac"/>
       </Stream></Connect>

4. Twilio reads the TwiML, opens a WebSocket
   to wss://example.com/twilio/media-stream.
   ────────────────────────────────────────────────────────────

   The first frames Twilio sends:
       { "event": "connected", "protocol": "Call" }
       { "event": "start", "start": {
            "streamSid": "MZ...",
            "callSid":   "CA1234567...",
            "customParameters": { "vertical": "hvac" }
         } }

5. Your edge handler (edge/src/twilio/media-stream.ts) sees "start":
   ────────────────────────────────────────────────────────────

   - Calls the core: POST /v1/sessions { surface: "phone", vertical: "hvac" }
     The core creates an app.conversations row and returns the
     session config.
   - Opens an outbound WebSocket to OpenAI Realtime:
         wss://api.openai.com/v1/realtime?model=gpt-realtime-2
         Authorization: Bearer ${OPENAI_API_KEY}
   - Sends session.update with the prompt + tools.

6. Twilio streams caller audio:
   ────────────────────────────────────────────────────────────

   Every 20 ms:
       { "event": "media", "media": { "payload": "<base64 μ-law>" } }

   For each frame, the edge:
   - decodes base64 → μ-law bytes
   - decodes μ-law → PCM-16 8 kHz
   - resamples 8 kHz → 24 kHz
   - re-encodes as base64 PCM
   - sends to OpenAI as input_audio_buffer.append

7. The model thinks, possibly calls tools (see running-agents.md),
   and streams audio back:
   ────────────────────────────────────────────────────────────

   { "type": "response.output_audio.delta", "delta": "<base64 PCM-24>" }

   The edge:
   - decodes base64 → PCM-16 24 kHz
   - resamples 24 kHz → 8 kHz
   - encodes as μ-law
   - emits to Twilio:
       { "event": "media", "streamSid": "MZ...",
         "media": { "payload": "<base64 μ-law>" } }

   Twilio plays it to the caller.

8. Loop steps 6-7 for the duration of the call.

9. Caller hangs up.
   ────────────────────────────────────────────────────────────

   Twilio sends:
       { "event": "stop", "stop": { "reason": "..." } }

   The edge:
   - closes the OpenAI WebSocket
   - calls the core: POST /v1/sessions/{id}/end
   - the core sets ended_at, fires the post_call hook
```

The whole thing is two WebSockets and a handful of HTTP calls.

---

## Setting it up: configuration walkthrough

### Step 1 — Get a Twilio account and a phone number

1. Sign up at twilio.com. They give you a trial credit and a sandbox
   number; you can buy real numbers from $1/month.
2. From the Console, **Phone Numbers → Manage → Buy a number**. Pick
   one with Voice capability.
3. Note the number you bought; you'll use it as the cockpit's voice
   line.

### Step 2 — Find your Twilio credentials

In the Twilio Console:

- **Account SID** — top-right header, copy.
- **Auth Token** — same place; click "show."

Put both in `.env`:

```
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+15125550150
```

### Step 3 — Expose your edge to the public Internet

Twilio needs to reach your `/twilio/voice` webhook. In production
that's a real domain pointing at your server. In dev, use a tunnel:

```bash
make tunnel
```

This runs `cloudflared tunnel --url http://localhost:8080` (or ngrok
as fallback). The output looks like:

```
Your tunnel is at: https://drowsy-tarantula.trycloudflare.com
```

Copy that URL. Update your `.env`:

```
PUBLIC_BASE_URL=https://drowsy-tarantula.trycloudflare.com
```

`PUBLIC_BASE_URL` is what the edge uses to (a) generate TwiML
WebSocket URLs and (b) verify Twilio signatures. It must match the
public host Twilio is actually calling.

### Step 4 — Wire the Twilio number to your webhook

In the Twilio Console, **Phone Numbers → Manage → Active Numbers →
{your number} → Voice Configuration**:

- **A Call Comes In** → Webhook → `https://drowsy-tarantula.trycloudflare.com/twilio/voice`
- HTTP method: `POST`

Save.

Now any call to that number will POST to your webhook.

### Step 5 — (Optional) Map numbers to verticals

If you have multiple Twilio numbers and want each to route to a
different vertical, set:

```
PHONE_VERTICAL_MAP=+15125550150=hvac,+15125550151=realestate
```

When a call comes in, the edge looks up the called number in this map
and includes the result as a `<Parameter>` in the TwiML.

### Step 6 — Restart and dial

```bash
make up           # pick up the new .env
make ps           # confirm containers are healthy
```

Dial your Twilio number from any phone. The cockpit should answer.
You should see the call appear in `/conversations` in real time.

---

## Webhook signature verification

When Twilio calls your `/twilio/voice` endpoint, it includes a
`X-Twilio-Signature` header. The edge verifies this header against
your Auth Token to confirm the request is genuine:

```typescript
import twilio from 'twilio';

const valid = twilio.validateRequest(
  settings.twilioAuthToken,
  signature,
  url,             // must match exactly: scheme + host + path + query
  form,            // the POST body fields
);
if (!valid) {
  reply.code(403);
  return 'invalid signature';
}
```

If `PUBLIC_BASE_URL` doesn't match the URL Twilio is calling (e.g.
because your tunnel restarted and got a new URL), this verification
fails and you'll see `twilio_signature_invalid` in the edge logs.

This is the most common Twilio integration bug. Always check
`PUBLIC_BASE_URL` first.

---

## What the WebSocket actually carries

Twilio's Media Streams events:

```json
// connection setup
{ "event": "connected", "protocol": "Call", "version": "1.0.0" }

// stream start; carries call metadata + custom params
{ "event": "start",
  "sequenceNumber": "1",
  "start": {
    "accountSid": "AC...",
    "streamSid":  "MZ...",
    "callSid":    "CA...",
    "tracks":     ["inbound"],
    "mediaFormat": { "encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1 },
    "customParameters": { "vertical": "hvac" }
  }
}

// audio (every 20 ms)
{ "event": "media",
  "sequenceNumber": "42",
  "media": {
    "track":     "inbound",
    "chunk":     "42",
    "timestamp": "840",
    "payload":   "<base64 μ-law, 160 bytes raw = 8 kHz × 20 ms>"
  },
  "streamSid": "MZ..."
}

// optional sync marker
{ "event": "mark", "mark": { "name": "your-mark-name" }, "streamSid": "MZ..." }

// stream stop
{ "event": "stop", "stop": { "accountSid": "AC...", "callSid": "CA..." }, "streamSid": "MZ..." }
```

Frames you send back to Twilio (only `media` and `mark`):

```json
{ "event": "media", "streamSid": "MZ...",
  "media": { "payload": "<base64 μ-law>" } }
```

Twilio buffers and plays them at 8 kHz to the caller.

---

## Latency considerations

Phone audio has a tighter latency budget than browser audio because
PSTN echo characteristics are unforgiving.

Targets:

- **Twilio → edge:** ~30 ms (network)
- **edge codec / resample:** <5 ms per frame
- **edge → OpenAI:** ~30 ms (network)
- **OpenAI thinks + responds:** the bulk
- **OpenAI → edge:** ~30 ms
- **edge codec / resample:** <5 ms
- **edge → Twilio:** ~30 ms
- **Twilio → caller:** ~50 ms (PSTN delays)

End-to-end first-response p50: ~1.5 s, dominated by the model.

To hit p99, you need:

- Edge in the same region as Twilio's media stream pop. Twilio
  publishes their pop locations; pick the closest cloud region.
- Edge with a low-jitter network — avoid noisy neighbors on shared
  hosts.

---

## SIP, PSTN, and how the call actually reaches Twilio

Most of this is invisible to your application, but it's worth
understanding once.

```
Homeowner's phone                   Carrier (AT&T, Verizon)
     │                                       │
     │ ──── analog or VoLTE ────────────────►│
                                             │
                            Inter-carrier   │
                            interconnect     │
                            (SS7 + SIP)      ▼
                                       Twilio SIP edge
                                             │
                            Twilio's internal│
                            voice stack      ▼
                                      Programmable Voice
                                             │
                            Webhook + Media  │
                            Streams          ▼
                                       Your edge service
```

The "PSTN" part covers carrier-to-carrier signaling and audio. SS7 is
the legacy signaling protocol still used for landline routing. SIP
(Session Initiation Protocol) is the modern VoIP equivalent. You
don't speak either — Twilio terminates them and hands you the audio
over WebSocket.

For deeper integration scenarios (e.g. you want to do SIP REFER for
warm transfers), Twilio exposes those primitives via TwiML
(`<Refer>`, `<Dial>`, `<Conference>`). Out of scope for v1.

---

## Common Twilio integration bugs

| Symptom | Likely cause | Fix |
|---|---|---|
| Call rings but Aria never speaks | Webhook not reachable from internet | Check `make tunnel`; confirm Twilio Console webhook URL matches |
| `twilio_signature_invalid` in edge logs | `PUBLIC_BASE_URL` doesn't match the URL Twilio calls | Set `PUBLIC_BASE_URL` to your current tunnel URL |
| `Twilio cannot connect to media stream` | TwiML returns `wss://localhost/...` | Edge uses `PUBLIC_BASE_URL` to build the wss URL — set it correctly |
| Caller hears their own voice echoed | OpenAI `audio.output` is reaching them via Twilio fast enough but the edge isn't decoding inbound audio | Check `cockpit-edge` logs; usually a μ-law decode error |
| Call hangs up after 30 s of silence | Twilio's heartbeat-based timeout | Edge isn't sending audio back; OpenAI session never opened |
| `Model "gpt-realtime-2" is only available on the GA API` | `OpenAI-Beta` header is being sent | Remove it (already done in this codebase) |

The operations runbook in [docs/ops.md](../ops.md) covers more
recovery procedures.

---

## Outbound calling (out of scope for v1)

This codebase only handles **inbound** calls. To make outbound calls
(the agent dials someone), you'd:

1. Call Twilio's REST API: `POST /Calls` with `From`, `To`, and a
   `Url` pointing at a TwiML endpoint.
2. The TwiML endpoint returns the same `<Connect><Stream>` document
   our `/twilio/voice` does today.
3. Twilio dials the recipient; on answer, it opens the media stream
   to your edge.

The edge code path is identical from there. The new piece is the
outbound REST call. Out-of-scope for v1, kept clean for future work.

---

## Where to read next

- The WebSocket bridge in code: [realtime-websocket.md](../concepts/realtime-websocket.md).
- Operations recovery procedures: [docs/ops.md](../ops.md).
- The full Twilio Programmable Voice docs: <https://www.twilio.com/docs/voice>
- Media Streams reference: <https://www.twilio.com/docs/voice/twiml/stream>
