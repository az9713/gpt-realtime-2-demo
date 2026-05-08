# Voice Agents — the cockpit's primary loop

> **OpenAI guide:** [Voice Agents](https://developers.openai.com/api/docs/guides/voice-agents)
> **Where it lands:** the entire cockpit. This is the spine that connects the
> human to the tools.

---

## What is a "voice agent"?

A **voice agent** is software that has a spoken conversation with a
human and acts on their behalf — looking things up, scheduling things,
making calls into other systems. It's an LLM with three superpowers
strapped to it:

1. **Ears** — speech-to-text, so it can understand what you said.
2. **A voice** — text-to-speech, so it can talk back to you.
3. **Hands** — *tool calling*, so it can press the buttons you would
   have pressed yourself.

For decades, building this required gluing together five separate
products (a telephony provider, a speech recognizer, an LLM, a TTS
engine, an orchestration layer). With OpenAI's Realtime models — the
ones that started shipping in late 2024 with `gpt-4o-realtime-preview`
and went GA in 2026 with `gpt-realtime-2` — a single API does all of it
behind one WebSocket. You speak in; the model speaks out; in between,
it can call your tools.

---

## The core idea: one loop, repeated forever

A voice agent's job is to run *one loop* over and over for as long as
the conversation lasts:

```
┌─ user speaks ─────────────────────────────────┐
│                                               │
│  1. capture audio frame                       │
│  2. send to model                             │
│  3. model decides:                            │
│       a) keep listening (user still talking)  │
│       b) speak a response                     │
│       c) call a tool, then speak              │
│       d) silently update its memory           │
│  4. model emits audio frames                  │
│  5. play to user                              │
│                                               │
└──────────────────────── back to top ──────────┘
```

Every voice agent — Alexa, Siri, customer-service bots, this
cockpit — implements some version of this loop. The differences are
in *which tools step 3c can reach*, *what guardrails sit on those
tools*, and *what data persists between turns*.

---

## What the cockpit's loop actually does

In this codebase the loop runs across two services. Here's the
play-by-play for the HVAC dispatcher case.

```
  Caller: "Do you have a 440 volt capacitor for a Carrier 58STA?"

  EDGE (Node)                          CORE (Python)
  ────────────                          ──────────────

  receives PCM audio from
  Twilio, resamples to 24 kHz,
  base64-encodes, forwards to
  OpenAI Realtime as
  input_audio_buffer.append events

  ↓
  OpenAI VAD detects silence,
  ↓ commits buffer, runs the model
  ↓
  model emits a function_call
  in response.done.output[]:
  {
    "name": "parts_lookup",
    "arguments": "{\"part_description\":\"capacitor\",
                   \"model_number\":\"Carrier-58STA\"}"
  }

  → POST /v1/sessions/{id}/tool-calls --→  ToolDispatcher.execute(req, ctx)
                                              │
                                              │ 1. append turn (role=tool)
                                              │ 2. create tool_call row (status=requested)
                                              │ 3. emit trace: tool.requested
                                              │ 4. run guardrail.before_tool_call
                                              │    (PII redactor, vertical hooks)
                                              │ 5. tool.blast_radius == "read" → no approval
                                              │ 6. await tool.handler(req, ctx)
                                              │       └─→ reads parts.json fixture
                                              │ 7. update tool_call (status=executed,
                                              │                        result_json)
                                              │ 8. emit trace: tool.executed
                                              │ 9. return ToolCallResult
                                              ↓
  ← {"tool_call_id":..., ←─────────────── ToolCallResponseModel
      "status":"executed",
      "result":{
         "matches":[{"part_number":"P-CAP-440-A","price_usd":28.50,...}],
         "total_matches":2}}

  forwards to OpenAI as
  conversation.item.create
  with type "function_call_output",
  then emits response.create

  ↓
  model speaks: "We've got 12 of part P-CAP-440-A in stock at
  $28.50 each. Want me to get one on a truck for you?"
  ↓
  edge resamples 24 kHz → 8 kHz, encodes μ-law, ships to Twilio,
  Twilio plays to caller's phone.
```

That's one full turn. The next turn does the same thing.

The loop has been wired so it works **identically** whether the surface
is a phone or a browser:

- Phone path: Twilio Media Stream WebSocket ↔ edge ↔ OpenAI ↔ core.
- Browser path: browser WebSocket ↔ edge ↔ OpenAI ↔ core.

The edge does the audio-format adaptation; the core never knows or
cares which surface it's serving.

---

## "Do this for me" — the cockpit's primary loop

The OpenAI Voice Agents guide frames the agent's job as carrying out
*intents* — "do this for me" — rather than answering questions. That's
the cockpit's framing too.

A "do this for me" intent looks like:

- *"Move my Wednesday job to Tuesday at 8."* → fires `schedule_lookup`
  (read), then `schedule_move` (dangerous, gated).
- *"Send Aldo's truck to the Smith job."* → fires
  `dispatch_truck` (dangerous, gated).
- *"Pull up Maria Alvarez's account."* → fires `customer_lookup`
  (read).

The platform's job is to make this work the same way every time:

| Property | How the cockpit guarantees it |
|---|---|
| Intents end in real action | Every tool is a real Python function with a typed schema. The model can't make up a tool name; the registry rejects unknowns. |
| Dangerous actions are gated | Tools declare `blast_radius`. Anything `dangerous` blocks on an approval row before executing. |
| Failures are visible | Every tool call writes a row to `tool_calls` with status. Every failure emits a `tool.failed` trace event. |
| Behavior is reproducible | Each conversation is fully reconstructible from turns + tool_calls + trace_events. `make replay CONV=<uuid>` rebuilds it. |

---

## What the model has to do well

A voice agent is harder than a text-based chatbot because the model
has to keep three things in flight simultaneously while speaking:

1. **Listen for new user input** — even mid-response, the user may
   interrupt with a correction. (`turn_detection: semantic_vad` lets
   the model handle this gracefully.)
2. **Decide whether to call a tool** — the model has to recognize
   "the user wants me to look something up" vs. "the user wants me
   to chat" without explicit tagging.
3. **Maintain persona** — Aria's voice and tone come from the
   `prompt.md` in the vertical pack. The model has to keep speaking
   *as Aria* while doing all of the above.

The Realtime model handles (1) and (3) natively. The cockpit handles
(2) by giving the model a tightly typed tool registry up front in the
`session.update` event — every tool's name, description, and JSON
schema. The model uses those descriptions to decide when to call
each one.

---

## Why this is built as a *platform*, not a single agent

A common mistake is to write one voice agent for one use case
(answering customer-service calls for one company). The cockpit's
spec calls this out explicitly:

> Verticals (HVAC dispatcher, real-estate, founder ops, telehealth)
> are *configurations* on the platform, not separate apps.

Concretely: the same `core/` and `edge/` codebases serve any vertical.
Adding a new vertical means writing a new directory at
`verticals/<name>/` with the right files — no platform changes.
The cockpit can switch active verticals at session start, so a
single operator could plausibly run multiple verticals out of one
deployment.

---

## How to verify the loop is healthy

1. **First-response latency under 1.5 s p50 on a local network.**
   Measured at the edge as the time from "user finished speaking"
   (input_audio_buffer commit) to "first agent audio frame emitted."
2. **No hung sessions on browser close.** The edge listens for the
   browser WebSocket close and tears down the OpenAI session and the
   core session in order.
3. **Every voice question that should fire a tool, does.** This is
   what the [scenario eval suite](../eval-format.md) catches:
   each `verticals/hvac/scenarios/*.yaml` lists expected tool calls;
   `make test-eval` runs them and fails if any are missing.

---

## Where to read next

- For how the audio actually moves around: [realtime-webrtc.md](realtime-webrtc.md)
  (browser) or [realtime-websocket.md](realtime-websocket.md) (phone).
- For how the model decides when to call a tool: [realtime-models-prompting.md](realtime-models-prompting.md).
- For how dangerous tools get held: [guardrails-approvals.md](guardrails-approvals.md).
- For the data the platform persists: [realtime-conversations.md](realtime-conversations.md).
