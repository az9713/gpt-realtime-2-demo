# Voicemail / overflow handler

> **Whisper feature 1 of 5.** Solo whisper session.
> **Where it lives:** the Twilio webhook + a per-vertical
> `business_hours` config. No agent persona, no tools, no risk of
> hallucinated commitments — just a recorded greeting and a
> transcribed message.

---

## What it solves

Outside the dispatcher's working hours, inbound calls today either
hit the agent (which would happily commit Aria to schedule changes
with no human in the loop) or get a static IVR. Neither is great.

Voicemail mode replaces both with a third option: a recorded greeting
followed by a whisper-only capture session. The caller leaves a
message; the dispatcher reads the transcript in the cockpit when they
log on; nothing in the agent's tool registry ever fires.

---

## How it activates

Three conditions must all be true:

1. The caller's destination number is mapped to a vertical via
   `PHONE_VERTICAL_MAP` (or there's a single configured vertical).
2. The vertical's `pack.yaml` has `business_hours` set AND `voicemail`
   in its `modes:` list.
3. The current local time (per `business_hours.tz`) falls outside the
   configured `open`/`close`/`days` window.

When all three hold, the Twilio webhook serves a different TwiML.

---

## End-to-end flow

```
1. Caller dials.

2. Twilio POSTs /twilio/voice on the edge.

3. Edge looks up the called number → vertical → fetches:
       GET /v1/verticals/<vertical>/business-status

4. Core's verticals/business_hours.is_open_now() evaluates
   tz + days + open/close window. Returns:
       { open: false, voicemail_greeting: "<text from voicemail.md>",
         supports_voicemail: true }

5. Edge returns voicemail TwiML (buildVoicemailTwiml):
       <Response>
         <Say voice="alice">…greeting…</Say>
         <Connect>
           <Stream url="wss://example.com/twilio/media-stream">
             <Parameter name="vertical" value="hvac"/>
             <Parameter name="mode" value="voicemail"/>
           </Stream>
         </Connect>
       </Response>

6. Twilio plays the greeting, then opens the media-stream WebSocket.

7. Edge's media-stream handler sees customParameters.mode === 'voicemail'
   and calls startVoicemailSession() instead of the agent path.
   That:
     • POSTs /v1/sessions { surface:'phone', vertical:'hvac', mode:'voicemail' }
       Core creates the conversations row but does NOT attach an agent
       runtime (mode is in _AGENTLESS_MODES).
     • Opens a TranscriptionSession solo (whisper-only WS).

8. Twilio streams the caller's audio. Edge decodes μ-law,
   resamples 8 kHz → 24 kHz, base64-encodes, forwards to whisper.

9. Whisper emits 'conversation.item.input_audio_transcription.completed'
   events. TranscriptionSession persists each via
       POST /v1/sessions/{id}/transcript  (model='whisper').

10. Caller hangs up → Twilio sends 'stop' → edge closes whisper WS,
    POSTs /v1/sessions/{id}/end. Core fires the post_call hook.

11. Post_call hook (HVAC: verticals/hvac/post_call.py) sees
    ctx.mode == 'voicemail' and writes a voicemail-shape summary:
       /data/post-call/<conv-id>.json
       {
         "kind": "voicemail",
         "transcript": "...",
         "intent": ["schedule"],   ← from keyword regex
         "callback_phone": "+15125550123",   ← from phone regex
         ...
       }
```

---

## Configuration — what each knob does

```yaml
# verticals/hvac/pack.yaml

modes:
  - realtime2
  - translate
  - notetaker
  - voicemail        # ← required for voicemail TwiML to be served

business_hours:      # ← required; if absent, the vertical is always-open
  tz: America/Chicago
  open: "09:00"
  close: "17:00"
  days: [1, 2, 3, 4, 5]   # ISO weekday: 1=Mon, 7=Sun

voicemail_greeting: voicemail.md   # ← markdown file in the pack dir
```

```markdown
<!-- verticals/hvac/voicemail.md -->
You've reached the after-hours line for the HVAC company. Our office
is closed right now. Please leave a message after the tone — your
name, the address with the unit, and a phone number. The dispatcher
will call you back first thing in the morning. If this is a safety
emergency such as a gas leak or carbon monoxide alarm, please hang
up and dial 911.
```

The `voicemail_greeting` value is a relative path inside the pack;
the loader reads its content at startup and surfaces it on
`VerticalPack.voicemail_greeting`. The Twilio `<Say>` element speaks
that text with `voice="alice"`.

For production deployments where the greeting voice quality matters,
swap the `<Say>` for `<Play>` with a pre-recorded MP3 — but that's a
deployment concern, not a code change.

---

## Window-edge cases the predicate handles

The `is_open_now()` predicate
(`core/src/cockpit_core/verticals/business_hours.py`) supports:

- IANA timezone names (e.g. `America/Chicago`, `Europe/London`,
  `Asia/Tokyo`). Required `tzdata` package on Windows; preinstalled
  on most Linux containers.
- ISO-weekday filtering — the `days` array can list any subset of 1-7.
- Midnight-wrapping windows — e.g. `open: "22:00", close: "06:00"` for
  an overnight on-call window. The predicate detects when `open >
  close` and treats the window as `[open, 23:59] ∪ [00:00, close]`.

Test coverage for these is in `core/tests/test_business_hours.py`.

---

## What the dispatcher sees

The cockpit's **Voicemails** tab (`/voicemails`) lists conversations
filtered by `mode=voicemail`:

```
┌──────────────────────────────────────────────────────────────┐
│  Voicemails                                                  │
│  ──────────                                                  │
│                                                              │
│  Received                  Vertical    Language    Duration  │
│  ────────                  ────────    ────────    ────────  │
│  May 8, 2026, 11:47 PM     hvac        en          47 s      │
│  May 8, 2026, 8:33 PM      hvac        en          1 m 12 s  │
│  May 7, 2026, 6:15 AM      hvac        es          2 m 04 s  │
└──────────────────────────────────────────────────────────────┘
```

Clicking a row opens the standard trace explorer at
`/conversations/<id>` — same UI, no special handling needed. Whisper
turns are tagged as `model: whisper` in the trace.

---

## Why this is safer than letting the agent answer

A voice agent is good at sounding helpful. That's exactly why you
don't want it answering calls when the dispatcher isn't around to
veto bad commitments. Concrete failure modes a voicemail flow
prevents:

| Risk | What the agent might do | Voicemail flow says |
|---|---|---|
| Hallucinated promises | "I'll have someone there in 30 minutes." | Doesn't speak; just records |
| Mid-night dispatch attempts | `dispatch_truck` request held for 60 s, eventually times out, agent improvises | Tools never load; can't fire |
| Off-hours pricing | Quotes a price the dispatcher would have refused | No pricing surface available |
| PII collection in unstaffed hours | Caller leaves card numbers on a voicemail with no one watching | PII redactor still runs on transcripts before persistence |

The voicemail mode is a *safety lever*, not a feature for callers who
prefer voicemail.

---

## What's NOT in v1

- **Configurable per-tool override.** All tools are bypassed in
  voicemail mode; you can't selectively allow read tools.
- **Real-time dispatcher pager.** Voicemails sit in the cockpit until
  someone refreshes. A future hook in `post_call.py` could integrate
  PagerDuty, Slack, etc.
- **Audio storage.** SPEC §13.2 — only transcripts persist. The
  `turns.audio_uri` column is reserved for a future S3-style backend.
- **Outbound callback.** The dispatcher reads the message and calls
  back manually.

---

## Operator how-to

For the step-by-step *how do I configure this for my vertical?*, see
[guides/configure-business-hours.md](../guides/configure-business-hours.md).

## Eval coverage

`verticals/hvac/scenarios/08_voicemail_after_hours.yaml` — drives the
runner with `expected_mode: voicemail` and asserts no tools fire.

## Where to read next

- The whisper plumbing: [reference/realtime-models-in-use.md](../reference/realtime-models-in-use.md).
- The Twilio bridge: [reference/twilio-integration.md](../reference/twilio-integration.md).
- The conversation store: [concepts/realtime-conversations.md](realtime-conversations.md).
