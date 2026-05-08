# Translate Mode — meeting companion via swapped model

> **OpenAI guide:** Realtime models — translate variant.
> **Where it lands:** the cockpit's mode switcher; the foundation for a future
> meeting overlay.

---

## What translate mode is

OpenAI ships three GA real-time models. Two are used in conversational
flow:

- **`gpt-realtime-2`** — the conversational default. Reasons,
  speaks, calls tools.
- **`gpt-realtime-translate`** — a sibling model purpose-built for
  passthrough translation. Listens in language A, speaks in language B.
  Doesn't reason, doesn't call tools.

The third model (`gpt-realtime-whisper`) participates as a *sidecar*
during translate sessions to capture the source-language transcript;
see [Bilingual capture](#bilingual-capture) below.

Switching from realtime-2 to translate is a small but careful
operation: tear down the old session, open a new one against the new
model, keep the conversation ID stable so traces and history flow on
the same timeline.

This codebase exposes that swap as **mode switching**, both manual
(operator click in the cockpit) and automatic (when the inbound
language is detected as non-English).

---

## When you'd use it

The HVAC scenario:

> A homeowner calls. They speak Spanish. The dispatcher (Reggie) only
> speaks English. Aria detects the language in the first three
> seconds, switches to translate mode, and starts relaying:
>
> - The Spanish caller hears Aria translate Reggie's English.
> - Reggie hears the Spanish caller's words rendered as English.
>
> The conversation flows. Reggie can ask clarifying questions in
> English; Aria translates. Aria does NOT call tools or follow the
> HVAC dispatcher persona while in translate mode — it's a
> straight-through translator.

A future "meeting overlay" use case:

> The dispatcher is in a video meeting with a Spanish-speaking
> general contractor. The cockpit attaches to the meeting tab's audio,
> runs in translate mode, and overlays English captions on screen.
> Same architecture — just a different surface piping audio in and
> out.

The single core, single edge, single agent runtime serve both.

---

## The mechanics of a switch

The session-switch protocol has three steps:

```
1. Operator (or auto-detector) calls:
       POST /v1/sessions/{id}/mode { "mode": "translate" }

2. Core does:
       app.conversations.mode := 'translate'  -- persist
       emit trace: mode.switch
       publish redis: session:<id>  { kind: 'mode.switch', mode: 'translate' }

3. Edge sees the session-event WS message, calls:
       session.switchModel('translate')
       which closes the OpenAI WebSocket and re-opens against
       gpt-realtime-translate, then resends session.update with
       the translate-appropriate instructions.
```

Two things to notice:

- **The conversation ID is unchanged.** The Postgres row, the trace
  events, the cockpit's open WebSocket — all continue uninterrupted.
  The only thing that's different is which model is on the other end.
- **The audio path is unchanged.** The browser/Twilio side keeps
  flowing PCM frames; the edge keeps decoding/encoding. Only the
  internal OpenAI WS gets re-opened.

Under the hood, in `edge/src/openai/session.ts`:

```ts
async switchModel(mode: 'realtime2' | 'translate'): Promise<void> {
  const newModel = mode === 'translate'
    ? this.settings.openaiTranslateModel
    : this.settings.openaiRealtimeModel;
  if (newModel === this.model) return;

  this.close();           // close old WS
  this.model = newModel;
  await this.open();      // open new WS, send session.update
}
```

A 1-2 second pause is normal during the swap. The user might hear a
brief silence; the cockpit shows a pending state via the trace.

---

## Auto-detection

The auto-flip path (Phase 7 task 34) uses a tiny language identifier
on the edge, in `edge/src/voice-intent/lang-id.ts`:

```ts
export type Lang = 'en' | 'es' | 'fr' | 'unknown';

export function classifyLanguage(text: string): Lang {
  const lower = text.toLowerCase();
  const score: Record<KnownLang, number> = {
    en: ENGLISH_HINTS.reduce((s, h) => s + (lower.includes(h) ? 1 : 0), 0),
    es: SPANISH_HINTS.reduce((s, h) => s + (lower.includes(h) ? 1 : 0), 0),
    fr: FRENCH_HINTS.reduce((s, h) => s + (lower.includes(h) ? 1 : 0), 0),
  };
  ...
}
```

A bigram-frequency lookup over recognized text. Crude, but enough to
distinguish "Hello, I need to schedule…" from "Hola, necesito
agendar…" with high enough precision to trigger a flip.

Production deployments would swap this for a small local model
(fastText-lid is the typical choice). The interface is `Lang =
classifyLanguage(text)` — implementation can change without
ripples.

The flow:

1. The first ~3 seconds of inbound transcript is collected (from
   OpenAI's user-transcript events).
2. `classifyLanguage(transcript)` runs.
3. If the result is non-English AND the active vertical's
   `auto_translate_non_english` flag is true, the edge calls
   `coreClient.switchMode('translate')`.

The HVAC pack opts in:

```yaml
# verticals/hvac/pack.yaml
auto_translate_non_english: true
```

---

## What the operator sees

The cockpit's Talk page has a mode badge and a manual toggle:

```
┌────────┐  ┌──────────────┐  ┌─────────────────────────┐  ┌──────────┐
│  Stop  │  │  REALTIME-2  │  │  Switch to Translate    │  │ 90457a44 │
└────────┘  └──────────────┘  └─────────────────────────┘  └──────────┘
```

When the mode switches (auto or manual), the badge updates in
real time via the per-session WebSocket subscription. The trace
explorer logs a `mode.switch` event so the operator can see the
boundary in the timeline.

---

## The persona during translate mode

`gpt-realtime-translate` is purpose-built to *not* take
conversational initiative — it relays, it doesn't reason. So the
prompt for translate mode is short and oriented around mechanics
rather than persona:

```markdown
You are a passthrough translator. When you hear language X, render it
in language Y. Do not summarize, paraphrase, or add commentary.
Do not call tools. Do not greet or say goodbye.
```

(In practice, the model has these defaults baked in; the prompt is a
reinforcement.)

When the session flips back to realtime2, the original Aria prompt is
resent in `session.update`. The agent resumes its dispatcher persona
and tools.

---

## Bilingual capture

When a session enters translate mode, a `gpt-realtime-whisper` sidecar
opens **lazily** on the first audio frame. Both transcripts persist
in `app.turns` — the translate model's target-language and whisper's
source-language — distinguished by `turns.model`.

```
inbound audio frames
        │
        ├──► RealtimeSession (gpt-realtime-translate)
        │            │
        │            ▼
        │     POST /transcript (model='gpt-realtime-translate', target language)
        │
        └──► TranscriptionSession (gpt-realtime-whisper)
                     │
                     ▼
              POST /transcript (model='whisper', source language)
```

Why lazy: opening a second OpenAI WebSocket adds ~200 ms of handshake.
For translate mode, that's hidden behind the user's first utterance —
the user has just spoken, the agent is already responding; the
sidecar catches up while the conversation continues. (For the audit
feature, the sidecar opens *in parallel* at session start instead;
completeness matters more than first-response latency. See
[concepts/audit-transcripts.md](audit-transcripts.md).)

The cockpit's trace explorer renders paired turns side-by-side so the
dispatcher can read both versions:

```
USER · es        Hola, necesito agendar
USER · whisper   Hola, necesito agendar un servicio
                 ↑ canonical (whisper) caught the second clause
                   the translate model dropped
```

This is also the data the audit divergence diff runs against when
audit is enabled on top of translate.

---

## Why mode switching, not a separate call

You might think: "couldn't translate just be a separate call?"
Architecturally, yes — but the user experience suffers:

- **For phone calls:** the caller is already on the line. Hanging up
  to "switch" is a terrible flow.
- **For browsers:** the operator can manually toggle without
  re-establishing audio.
- **For the trace:** keeping the same conversation ID means the trace
  shows the language flip as one event, not as two separate
  conversations the operator has to mentally splice.

The mode switch is in-place because the *conversation* is the
durable thing; the *model* is the swappable engine.

---

## Limitations of v1

1. **Two-language assumption.** v1 detects English vs non-English and
   flips on non-English. If the caller is multilingual or
   code-switches mid-call, the agent doesn't re-evaluate. Realistic
   future work: re-classify every N seconds.
2. **No "translate just this turn" mode.** If a Spanish-speaking
   caller drops one Spanish phrase into an English call, the entire
   session flips. A finer-grained "translate this segment" mode
   would need a model-side hook.
3. **No transcript bilingual rendering.** v1 stores whatever the
   model gave it. A future version could store both source and
   target and present both in the cockpit.

---

## How to verify it works

The HVAC eval suite includes a translate-flip scenario:

```yaml
# verticals/hvac/scenarios/04_spanish_translate_flip.yaml
id: spanish_translate_flip
description: |
  Spanish-speaking caller is detected; the session flips to translate
  mode within the first few seconds and stays there.
vertical: hvac
language: es

actions:
  - kind: language
    language: es
  - kind: mode
    mode: translate

expected_mode: translate
```

`make test-eval` runs it. Real dial-in testing requires a Spanish
speaker (or a recorded Spanish prompt) and a Twilio number.

---

## Where to read next

- The session-switching protocol on the edge:
  [realtime-websocket.md](realtime-websocket.md).
- The cockpit's mode badge / toggle: `frontend/src/cockpit/ModeBadge.tsx`,
  `ModeToggle.tsx`, `TalkPage.tsx`.
- The model itself: [reference/gpt-realtime-2.md](../reference/gpt-realtime-2.md).
