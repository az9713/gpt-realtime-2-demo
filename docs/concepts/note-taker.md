# Note-taker mode

> **Whisper feature 2 of 5.** Solo whisper session.
> **Where it lives:** the cockpit's "Notes only" button beside Talk.
> **Difference from Talk:** no agent persona, no tools, no audio reply
> from any model. Whisper transcribes silently into `app.turns`.

---

## What it solves

Sometimes the dispatcher takes a call directly — same caller, same
business, but a question Aria isn't suited for (a sensitive
billing dispute; a personal favor; a long technical conversation
with another tech). Today, none of that gets transcribed. Notes get
lost.

Note-taker mode is a third surface state: dispatcher converses with
the caller as themselves; whisper silently captures the audio into
durable transcripts. The conversation appears in the standard
`/conversations` view alongside Aria-driven calls.

---

## How it differs from Talk

```
Talk (mode=realtime2):           Notes only (mode=notetaker):
─────────────────────            ──────────────────────────────
  RealtimeSession                  TranscriptionSession solo
  agent persona (Aria)             no persona
  tool registry loaded             no tools
  audio output to user             no audio output
  approvals + guardrails           neither — passive capture
  trace events on every step       trace events on session start/end only
  preambles                        (irrelevant)
```

In code: `edge/src/webrtc/signaling.ts` branches on the `mode` query
param. `mode=notetaker` calls `startNotetakerSession()` instead of
`startAgentSession()`; the former opens a `TranscriptionSession`
directly with no `RealtimeSession` ever instantiated. The whisper
WebSocket connects to `wss://api.openai.com/v1/realtime?intent=transcription`
(distinct from the conversational endpoint — see
[reference/realtime-models-in-use.md](../reference/realtime-models-in-use.md)).

---

## End-to-end flow

```
1. Dispatcher logs into the cockpit (/).

2. Dispatcher clicks "Notes only" instead of "Talk".

3. Frontend opens:
       ws://localhost:8080/v1/voice/browser?vertical=hvac&mode=notetaker

4. Edge's signaling.ts sees mode=notetaker; calls
   startNotetakerSession() which:
     • POSTs /v1/sessions { surface:'browser', vertical:'hvac', mode:'notetaker' }
       Core creates the conversations row in agentless mode (no
       runtime attached, no tools loaded, persona returned as "").
     • Opens a TranscriptionSession solo against gpt-realtime-whisper.
     • Sends 'session.created' back to the browser with mode='notetaker'.

5. Browser's TalkPage sets recording=true and starts capturing mic
   audio via the same getUserMedia + AudioContext pipeline that Talk
   mode uses. Audio frames go over the WebSocket as 'audio.append'.

6. Edge forwards each frame to whisper. Whisper detects end-of-
   utterance, emits transcription.completed, TranscriptionSession
   persists with model='whisper'.

7. The browser shows transcripts arriving via 'transcript.user'
   messages. There is no audio playback from the model in this mode.

8. Dispatcher clicks Stop. The WebSocket closes. Edge calls
   /v1/sessions/{id}/end. Core fires the post_call hook.

9. The HVAC post_call hook sees ctx.mode == 'notetaker' and writes
   a notetaker-shape summary:
       /data/post-call/<conv-id>.json
       {
         "kind": "notetaker",
         "mode": "notetaker",
         "turn_count": 7,
         "transcript": "[user] hi maria what's going on...\n[user] ..."
       }
   No tool roll-up; no follow-up extraction (the dispatcher is
   responsible for follow-ups themselves).
```

---

## v1 scope: dispatcher-side capture only

A subtle limitation: when the dispatcher uses note-taker mode while
also being on a phone call with the caller, **only the dispatcher's
microphone is captured**. The caller's audio is on a separate path
(PSTN if they called a Twilio number; another browser otherwise).

To capture both sides, you'd need to either:

- bridge the two audio streams via a Twilio conference call
  (`<Conference>` TwiML), then run note-taker against the dispatcher's
  side of the conference, OR
- attach a meeting-tab capture via `getDisplayMedia({ audio: true })`
  and route both into the same WebSocket.

Both are post-v1. The current note-taker mode is "dispatcher-side
captioning" — useful for note-taking *during* the call, not as a
single canonical transcript of the call.

---

## When to use which mode

| Need | Mode |
|---|---|
| Caller has a routine question (parts, schedule, warranty) | **Talk** (realtime2) — Aria handles it |
| Caller is non-English | **Talk** (auto-flips to translate) |
| Sensitive customer issue, dispatcher takes the call | **Notes only** (notetaker) |
| After-hours overflow | **Voicemail** (auto, via business hours) |
| Internal staff conversation that should still be captured | **Notes only** |
| Anything where the dispatcher wants to *prevent* tool execution | **Notes only** (the agent literally cannot fire tools in this mode) |

---

## Configuration

```yaml
# verticals/<name>/pack.yaml

modes:
  - realtime2
  - translate
  - notetaker        # ← required, otherwise create_session 400s
```

That's the only knob. The cockpit's button is unconditional; pressing
it always tries to create a notetaker session. If the vertical
doesn't list `notetaker`, the core returns:

```
HTTP 400  "vertical 'hvac' does not support mode 'notetaker'"
```

To remove note-taker from a vertical, drop it from the pack's modes
list. The cockpit button will still appear; clicks will fail with the
400; that's a v1.5 polish item.

---

## What's NOT in v1

- **Both-sides capture** — see "v1 scope" above.
- **Per-call control over which whisper model** — always
  `gpt-realtime-whisper`. If you want a faster/cheaper variant,
  point `OPENAI_WHISPER_MODEL` at it; affects all whisper sessions
  globally.
- **In-cockpit dispatcher annotations** — the transcript is read-only.
  A future feature could let the dispatcher add bullet notes alongside
  the transcript.
- **Pause/resume during note-taker session** — Stop ends the session;
  there's no pause.

---

## Eval coverage

`verticals/hvac/scenarios/07_notetaker_session.yaml` — runs with
`expected_mode: notetaker` and `expected_tool_calls: []`.

`core/tests/test_notetaker_post_call.py` — verifies the
notetaker-shape summary AND that realtime2 summaries are unchanged
(non-regression net).

## Where to read next

- The whisper plumbing: [reference/realtime-models-in-use.md](../reference/realtime-models-in-use.md).
- The browser audio path: [concepts/realtime-webrtc.md](realtime-webrtc.md).
- Voicemail mode (other solo whisper feature): [concepts/voicemail.md](voicemail.md).
