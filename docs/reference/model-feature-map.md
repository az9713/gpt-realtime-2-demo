# Model → Feature Map

A single-page map from each of OpenAI's three GA Realtime models to
every cockpit feature that uses it. Bookmarkable; meant to answer
*"which model powers X?"* without scrolling.

For deep dives on each model and feature mechanics, see
[reference/realtime-models-in-use.md](realtime-models-in-use.md).

---

## Quick lookup

```
gpt-realtime-2 ──────────► browser Talk · phone calls · tools · approvals · preambles · per-tool persona · trace pipeline · evals 01–05
                                                                                                                            └─ tests/eval/test_hvac_scenarios.py

gpt-realtime-translate ──► translate mode auto-flip · cockpit manual toggle · /v1/sessions/{id}/mode · ModeBadge · eval 06
                                                                                                                  └─ verticals/hvac/scenarios/06_translate_bilingual.yaml

gpt-realtime-whisper  ───► voicemail (Phase 4) · note-taker (Phase 3) · bilingual sidecar (Phase 2) · audit transcripts (Phase 5) · synthesize-eval (Phase 6)
                                                                                                                                       └─ scripts/synthesize-eval.py
```

---

## `gpt-realtime-2` — conversational default

The model behind every "Aria" interaction with tools.

| Feature | Lives in | Notes |
|---|---|---|
| Browser cockpit Talk button | `frontend/src/cockpit/TalkPage.tsx`, `edge/src/webrtc/signaling.ts` | Default mode for browser surface |
| Phone bridge (Twilio inbound) | `edge/src/twilio/media-stream.ts`, `edge/src/twilio/webhook.ts` | Default mode for phone surface |
| Function call dispatch loop | `edge/src/openai/session.ts`, `core/src/cockpit_core/agent/dispatch.py` | Reads `response.done.output[]` for `function_call` items |
| Tool registry serialization | `core/src/cockpit_core/agent/registry.py` → `schemas()` | Sent in `session.update.tools` |
| Persona + prompt | `verticals/<name>/prompt.md` | Sent in `session.update.instructions` |
| Preambles | `verticals/<name>/preambles.yaml` | "Let me pull up that part" before each tool call |
| Approval flow (voice + cockpit click) | `core/src/cockpit_core/agent/approvals.py` | Approval phrase = the preamble for dangerous tools |
| Trace pipeline events | `core/src/cockpit_core/observability/tracer.py` | `turn.user`, `turn.agent`, `tool.requested`, `tool.executed`, etc. |
| User transcript persistence | `edge/src/openai/session.ts` → `pushTranscript(..., 'user', text, latency, this.model)` | `app.turns.model` set to `gpt-realtime-2` |
| Agent transcript persistence | same, role='agent' | `app.turns.model` set to `gpt-realtime-2` |
| HVAC eval scenarios 01–05 | `verticals/hvac/scenarios/01_*.yaml` … `05_*.yaml` | All five drive realtime-2 |

**Activation:** every session that isn't translate/voicemail/notetaker.
**Wire:** `OPENAI_REALTIME_MODEL` env var → `Settings.openaiRealtimeModel`
→ `RealtimeSession` constructor ternary on `config.mode`.

---

## `gpt-realtime-translate` — passthrough translator

The model behind translate mode. No tools, no reasoning, just relays.

| Feature | Lives in | Notes |
|---|---|---|
| Translate mode session | `edge/src/openai/session.ts` → `switchModel('translate')` | Tears down realtime-2 WS and reopens against translate |
| Auto-flip on non-English | `edge/src/voice-intent/lang-id.ts` + `pack.yaml: auto_translate_non_english` | First ~3 s transcript classifier |
| Manual cockpit toggle | `frontend/src/cockpit/ModeToggle.tsx` → `POST /v1/sessions/{id}/mode` | Operator-driven |
| Mode badge UI | `frontend/src/cockpit/ModeBadge.tsx` | Renders REALTIME-2 / TRANSLATE / NOTES ONLY / VOICEMAIL |
| Mode-switch trace event | `core/src/cockpit_core/agent/lifecycle.py` → `switch_mode()` | Recorded as `mode.switch` |
| Bilingual transcript capture | (sidecar — see whisper section) | Whisper sidecar opens lazily on first audio in translate mode |
| HVAC eval scenario 06 | `verticals/hvac/scenarios/06_translate_bilingual.yaml` | `expected_mode: translate` |
| HVAC eval scenario 04 (legacy translate flip) | `verticals/hvac/scenarios/04_spanish_translate_flip.yaml` | The original auto-flip eval |

**Activation:** any session where `config.mode === 'translate'`,
either at session start (via `CreateSessionBody.mode`) or after
`POST /v1/sessions/{id}/mode`.
**Wire:** `OPENAI_TRANSLATE_MODEL` env var → `Settings.openaiTranslateModel`
→ `RealtimeSession.switchModel`.

---

## `gpt-realtime-whisper` — transcription specialist

Used in two operational shapes (solo and sidecar) across five
features. The shared class is `TranscriptionSession`
(`edge/src/openai/transcription.ts`).

| Aspect | Notes |
|---|---|
| Endpoint | `wss://api.openai.com/v1/realtime?intent=transcription` (no `model=` query) |
| Model selector | `audio.input.transcription.model` in the session.update payload |
| session.update shape | `session.type: "transcription"`; no `output_modalities`, `tools`, `instructions`, `audio.output`, or `turn_detection` |
| Why a different URL | GA distinguishes "realtime sessions" from "transcription sessions" at the URL level. See [docs/ops.md](../ops.md#whisper-transcription-session--endpoint-quirks). |

### Feature 1 — Voicemail / overflow handler (solo)

| Aspect | Lives in |
|---|---|
| Trigger | `edge/src/twilio/webhook.ts` calls `GET /v1/verticals/{name}/business-status` on every inbound call |
| Predicate | `core/src/cockpit_core/verticals/business_hours.py` → `is_open_now()` (IANA-tz aware, supports midnight-wrapping windows) |
| TwiML emission | `edge/src/twilio/routing.ts` → `buildVoicemailTwiml()` (`<Say>` + `<Connect><Stream mode=voicemail>`) |
| Whisper session | `edge/src/twilio/media-stream.ts` branches on `customParameters.mode === 'voicemail'` and opens `TranscriptionSession` solo |
| Per-vertical config | `verticals/<name>/pack.yaml` → `business_hours`, `voicemail_greeting` |
| Greeting script | `verticals/<name>/voicemail.md` |
| Post-call summary | `verticals/<name>/post_call.py` → `_voicemail_summary()` (transcript + intent + callback phone) |
| Cockpit page | `frontend/src/voicemails/VoicemailListPage.tsx` at `/voicemails` |
| Conversation list filter | `core/src/cockpit_core/api/conversations.py` → `?mode=voicemail` |
| Eval scenario | `verticals/hvac/scenarios/08_voicemail_after_hours.yaml` |

### Feature 2 — Note-taker mode (solo)

| Aspect | Lives in |
|---|---|
| Cockpit button | `frontend/src/cockpit/TalkPage.tsx` → "Notes only" button passes `?mode=notetaker` |
| Edge handler | `edge/src/webrtc/signaling.ts` → `startNotetakerSession()` opens `TranscriptionSession` solo, skips `RealtimeSession` and `startVoiceIntent` |
| Per-vertical opt-in | `verticals/<name>/pack.yaml` → `modes:` list must include `notetaker` |
| Agentless session creation | `core/src/cockpit_core/api/sessions.py` → `_AGENTLESS_MODES` skips runtime attach |
| Post-call summary | `verticals/<name>/post_call.py` → `_notetaker_summary()` (transcript-only, no tool roll-up) |
| ModeBadge label | `frontend/src/cockpit/ModeBadge.tsx` (NOTES ONLY) |
| Eval scenario | `verticals/hvac/scenarios/07_notetaker_session.yaml` |

### Feature 3 — Bilingual capture (sidecar — translate mode)

| Aspect | Lives in |
|---|---|
| Sidecar field on RealtimeSession | `edge/src/openai/session.ts` → `private sidecar: TranscriptionSession \| null` |
| Decision predicate | `RealtimeSession.shouldHaveSidecar()` → true when `mode === translate` or `auditTranscripts` |
| Lazy open trigger | `RealtimeSession.appendAudio()` calls `ensureSidecar()` on first audio in translate mode |
| Transcript persistence | `TranscriptionSession.handleEvent()` → `core.pushTranscript(..., model='whisper')` |
| Both transcript streams in app.turns | `app.turns.model` distinguishes `'whisper'` vs `'gpt-realtime-translate'` |
| Eval scenario | `verticals/hvac/scenarios/06_translate_bilingual.yaml` |

### Feature 4 — Audit transcripts (sidecar always-on)

| Aspect | Lives in |
|---|---|
| Per-vertical opt-in | `verticals/<name>/pack.yaml` → `audit_transcripts: true` |
| Pack loader surface | `core/src/cockpit_core/verticals/loader.py` → `VerticalPack.audit_transcripts` |
| Session config plumbing | `CreateSessionResponse.audit_transcripts` → edge passes to `RealtimeSession` opts |
| Always-on parallel open | `RealtimeSession.open()` calls `ensureSidecar()` if `auditTranscripts` (not lazy) |
| Divergence diff | `core/src/cockpit_core/observability/audit.py` → `compute_divergences()`, `classify_divergence()` |
| Storage | `core/src/cockpit_core/store/audit_divergences.py` → `app.audit_divergences` table (migration 0003) |
| Cron-friendly runner | `scripts/audit-divergences.py` (`make audit`) |
| API | `core/src/cockpit_core/api/audits.py` → `GET /v1/audits/divergences` |
| Cockpit page | `frontend/src/audit/AuditListPage.tsx` at `/audit` |

### Feature 5 — Eval generation (offline, transcripts → YAML)

| Aspect | Lives in |
|---|---|
| Synthesizer | `core/src/cockpit_core/eval/synthesize.py` → `synthesize_scenario()` |
| Operator CLI | `scripts/synthesize-eval.py` (`make synthesize-eval CONV=<uuid>`) |
| Output path | `verticals/<vertical>/scenarios/replay_<conv-prefix>.yaml` |
| Tests | `core/tests/test_synthesize_eval.py` (5 tests including round-trip through `run_scenario`) |

Note: Feature 5 doesn't open a live whisper WebSocket in v1. It reads
`app.turns.transcript` rows directly. Whisper is the *conceptual*
ground truth — when audit_transcripts is on, the whisper-sourced
turns are what synthesize-eval prefers. v1.5 is the seam where
whisper would re-transcribe stored audio (SPEC §13.2 reserves
`turns.audio_uri` for this).

---

## Sidecar lifecycle summary

| Active config | Sidecar at session start? | Sidecar on first audio? | Notes |
|---|---|---|---|
| `mode='realtime2'`, audit off | No | No | Default HVAC path |
| `mode='translate'`, audit off | No | **Yes** (lazy) | First audio triggers `ensureSidecar()` |
| `mode='realtime2'`, audit on | **Yes** (parallel) | No (already open) | `Promise.all([primary, sidecar])` |
| `mode='translate'`, audit on | **Yes** (parallel) | No | Audit dominates lazy logic |
| `mode='voicemail'` | No `RealtimeSession` at all | — | Solo whisper opened by media-stream.ts |
| `mode='notetaker'` | No `RealtimeSession` at all | — | Solo whisper opened by signaling.ts |

`RealtimeSession.shouldHaveSidecar()` and `ensureSidecar()` /
`closeSidecar()` are the three private methods that own this logic.
Sidecar errors never take down the primary session — they are logged
as warnings and the sidecar reference is dropped.

---

## Coverage check

```
                                              gpt-realtime-2  gpt-realtime-translate  gpt-realtime-whisper
─────────────────────────────────────────────────────────────────────────────────────────────────────────
HVAC dispatcher (browser + phone)                ✓
HVAC tools, approvals, traces                     ✓
Translate mode (manual + auto)                                       ✓
Bilingual transcript capture                                         ✓                       ✓ (sidecar)
Voicemail / overflow handler                                                                  ✓ (solo)
Note-taker mode                                                                               ✓ (solo)
Audit transcripts + divergence diff                                                           ✓ (sidecar)
Synthesize eval from real call                                                                ✓ (offline)
```

Every model has at least one production feature. Whisper carries the
broadest feature surface because it's the most versatile of the three
(no audio output, no reasoning — pure capture).

---

## Where to read next

- For full operational details on each whisper feature:
  [reference/realtime-models-in-use.md](realtime-models-in-use.md).
- For the model API itself (events, session.update shape, errors):
  [reference/gpt-realtime-2.md](gpt-realtime-2.md).
- Per-feature deep dives:
  - [concepts/voicemail.md](../concepts/voicemail.md)
  - [concepts/note-taker.md](../concepts/note-taker.md)
  - [concepts/audit-transcripts.md](../concepts/audit-transcripts.md)
  - [concepts/translate-mode.md](../concepts/translate-mode.md)
