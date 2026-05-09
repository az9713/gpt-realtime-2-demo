# Testing — what's covered and what isn't

A complete view of every test layer in this codebase, grouped by *how
it runs* rather than by feature. For each layer: what runs, what it
asserts, and the limitations.

The headline numbers as of `main` at the latest tested commit:

```
✓  61 Python tests          (core/tests/)
✓  27 Node edge tests       (edge/tests/)
✓   8 HVAC eval scenarios    (verticals/hvac/scenarios/)
✓   2 alembic migrations applied + verified
✓   3 OpenAI Realtime models exercised (live and via fixture)
✓   5 cockpit routes render (HTTP 200)
✓   3 WebSocket modes open cleanly (realtime2 / translate / notetaker)
✓   3 new API endpoints respond correctly (verticals, audits, mode-filter)
✓   2 operator scripts run end-to-end (synthesize-eval, audit)
```

---

## Test layers (at a glance)

| Layer | Where | Run with | Live deps |
|---|---|---|---|
| Python unit + integration | `core/tests/` | `make test-core` | mocks the store; no Postgres needed |
| Eval scenarios | `core/tests/eval/` driving `verticals/*/scenarios/*.yaml` | `make test-eval` | none (pure in-process) |
| Edge tests | `edge/tests/` | `make test-edge` | `MockOpenAIWebSocket` fixture; no live OpenAI |
| Backend lint | core + edge | `ruff` / `tsc` | none |
| Alembic migration apply | Postgres | `make migrate` | Postgres |
| Operator scripts | host CLI | `make synthesize-eval CONV=` / `make audit` | Postgres |
| Live OpenAI probes | edge container | ad-hoc Node script | OpenAI API key |
| Browser feature tests | Chrome via Claude-in-Chrome MCP | guided session | full stack up |

---

## 1. Python tests (`make test-core`)

**61 tests, ~2.5 s, no live infra.** Every test mocks the asyncpg
store. Strict ruff + mypy passes alongside.

| File | Tests | What it covers |
|---|---|---|
| `tests/test_pii.py` | 4 | PII redactor: emails, phones, SSNs, credit-card-shaped digit runs; `has_pii` predicate |
| `tests/test_registry.py` | 4 | `ToolRegistry`: register, dispatch, duplicate rejection, unknown-tool error, GA-shape `schemas()` output |
| `tests/test_guardrails.py` | 3 | Guardrail middleware composition: pre-hook chaining, tool-call blocker, post-call PII redaction |
| `tests/test_tracer.py` | 3 | Async-batched tracer: batches + flushes by size and interval; drops with counter when queue full; `stats()` shape |
| `tests/test_approval_state_machine.py` | 4 | `ApprovalManager`: voice resolution flows back to waiter, timeout resolution, double-resolve raises `IllegalApprovalTransition`, unknown id returns false |
| `tests/test_vertical_loader.py` | 4 | HVAC pack loads; dangerous tools have phrases; invalid pack dir raises; read tools have no approval |
| `tests/test_hvac_tools.py` | 5 | HVAC tool handlers against real fixture data: parts_lookup matches; warranty status; unknown truck; schedule_move mutates job; dispatch_truck assigns |
| `tests/test_turn_persistence.py` (note: implicitly via store) | — | Round-trip via store helpers, exercised through other tests |
| `tests/test_turn_model_tagging.py` | 2 | Phase 2: dual-model turns (whisper + agent) round-trip; pre-Phase-1 callers (no `model` arg) still work |
| `tests/test_notetaker_post_call.py` | 2 | Phase 3: notetaker summary shape (transcript-only, no tool roll-up); realtime2 summary unchanged (regression net) |
| `tests/test_business_hours.py` | 7 | Phase 4: weekday open, after-hours, weekends, midnight-wrapping windows, timezone translation, missing config (always-open default), HVAC pack surfaces business_hours config |
| `tests/test_audit.py` | 9 | Phase 5: WER on identical strings; paraphrase tolerance; omission/addition classification; mismatch threshold; turn pairing by ts within 5 s window; unmatched canonical → omission; unmatched agent → addition; clean-pair empty result |
| `tests/test_synthesize_eval.py` | 5 | Phase 6: basic shape; translate-mode session emits mode + language seed actions; dangerous tool records approval; unknown conv raises; **end-to-end synthesize → write yaml → run_scenario passes** |
| `tests/eval/test_hvac_scenarios.py` | 8 | Each YAML scenario in `verticals/hvac/scenarios/` runs through `run_scenario()` and asserts expected_tool_calls / expected_approvals / expected_mode |

### What this catches

- All pure-logic regressions in the agent runtime, store layer,
  observability, guardrails, and audit pipeline.
- Approval state-machine race conditions (concurrent voice + cockpit
  resolution).
- Eval-runner contract changes (a synthesized scenario must round-trip
  back through the runner — the killer test in
  `test_synthesize_eval.py::test_synthesized_scenario_runs_through_existing_runner`).

### What this *doesn't* catch

- Real Postgres behavior (constraints, transaction semantics, JSONB
  encoding under concurrency). Mitigated by the *integration* path in
  the operator-script tests below.
- Performance under load.

---

## 2. Eval scenarios (`make test-eval`)

**8 YAML scenarios under `verticals/hvac/scenarios/`** — runs the
agent dispatcher in-process against fixture data, asserts what tools
fired and what approvals resolved.

| Scenario | Type | What it asserts |
|---|---|---|
| `01_parts_lookup.yaml` | read tool, no approval | `parts_lookup` invoked with the right args |
| `02_schedule_move_approved.yaml` | dangerous + voice approval | `schedule_lookup` then `schedule_move` execute; approval resolved as `approved` via `voice` |
| `03_schedule_move_denied.yaml` | dangerous + cockpit denial | no `schedule_move` execution; approval resolved as `denied` via `cockpit` |
| `04_spanish_translate_flip.yaml` | mode flip | `expected_mode: translate`, no tools fire |
| `05_multi_tool_parallel.yaml` | three tools in one turn | all three fire; same model turn |
| `06_translate_bilingual.yaml` (Phase 2) | translate session | `expected_mode: translate`, no tools fire (passthrough) |
| `07_notetaker_session.yaml` (Phase 3) | notetaker mode | `expected_mode: notetaker`, no tools, no approvals |
| `08_voicemail_after_hours.yaml` (Phase 4) | voicemail mode | `expected_mode: voicemail`, no tools, no approvals |

### What this catches

- The "did Aria call the right tool?" question is exactly what evals
  answer. A change to `tools.py` arg names, a tweak to the dispatcher
  logic, an accidental mode regression — all caught.

### What this *doesn't* catch

- Audio-quality issues. The eval runner skips the audio plane; it
  drives the dispatcher with explicit `actions` instead of replaying
  recorded utterances against a fixture OpenAI player.
- Latency. Evals report pass/fail, not timing budgets.

---

## 3. Edge tests (`make test-edge`)

**27 tests, ~1 s, no live OpenAI.** Uses a `MockOpenAIWebSocket`
fixture (in `edge/tests/_fixtures/`) that EventEmitter-impersonates
the `ws` library so the unit-under-test can drive real session
lifecycle without ever touching the network.

| File | Tests | What it covers |
|---|---|---|
| `tests/audio.test.ts` | 5 | μ-law byte round-trip preserves sign; PCM↔μ-law length; base64 round-trip; 8 kHz↔24 kHz resample; identical-rate noop |
| `tests/lang-id.test.ts` | 4 | Language classifier returns en / es / fr / unknown for representative inputs |
| `tests/routing.test.ts` | 3 | TwiML builder: `verticalForNumber` mapping; `buildTwiml` emits correct WS URL + Parameter; `buildRejectTwiml` escapes XML |
| `tests/voicemail-routing.test.ts` (Phase 4) | 3 | `buildVoicemailTwiml` emits `<Say>` + `<Connect>` with `mode=voicemail` parameter; greeting XML-escaped; vertical absent → no Parameter |
| `tests/transcription.test.ts` (Phase 1, updated for endpoint fix) | 6 | `TranscriptionSession` opens the right URL (`?intent=transcription`, no `model=` query); session.update has `session.type=transcription`, `audio.input.transcription.model=<configured model>`, no `turn_detection`, no `output_modalities`, no `tools`; completed transcript event persists with `model='whisper'`; `appendAudio` emits `input_audio_buffer.append`; `isOpen` flips after `close()`; `roleLabel='agent'` honored; mock-mode (no API key) opens no socket |
| `tests/session-sidecar.test.ts` (Phase 2) | 6 | realtime2 mode: no sidecar; translate mode: sidecar opens **lazily** on first audio; switchModel translate→realtime2: sidecar closes; auditTranscripts=true: sidecar opens at session start; user transcript tags persisted turn with active model; `close()` tears down both primary and sidecar |

### What this catches

- The whisper endpoint contract is **pinned** by tests — any future
  attempt to put `model=` back in the URL or add `turn_detection`
  back to the payload will fail tests immediately.
- Sidecar lifecycle correctness: lazy-open semantics, parallel-open
  for audit, clean teardown.
- Audio-codec correctness for the Twilio bridge.

### What this *doesn't* catch

- Live OpenAI handshake quirks. Mitigated by the **live OpenAI probe**
  layer below.
- Real Twilio Media Stream framing under packet loss.

---

## 4. Backend lint and typecheck

| Check | Tool | What it enforces |
|---|---|---|
| Python lint | `ruff check src tests` | Style + bug-prone patterns; ASYNC240, S105 hardcoded passwords (with intentional `# noqa` on dev defaults), unused imports, redundant assignments |
| Python types | `mypy --strict src` (informational; not CI-blocking due to a few existing `aclose` and redis-ping `await` mypy quirks) | Strict typing, no untyped public functions |
| Edge typecheck | `tsc --noEmit` | Strict TypeScript including `noUncheckedIndexedAccess`, `noImplicitAny` |

---

## 5. Alembic migrations

Three forward-only revisions, applied via `make migrate`:

| Revision | Adds |
|---|---|
| `0001_initial` | Original 5 tables (conversations, turns, tool_calls, approvals, trace_events) |
| `0002_widen_modes` (Phase 1) | Relaxes `conversations.mode` CHECK from `('realtime2','translate')` to `('realtime2','translate','voicemail','notetaker')` |
| `0003_audit_divergences` (Phase 5) | New `app.audit_divergences` table with kind / score / agent_text / canonical_text / flagged_at columns |

**Test:** `make migrate` from a clean DB applies all three; `alembic
current` reports `0003_audit_divergences (head)`. Verified after every
deployment.

---

## 6. Operator scripts (`make audit`, `make synthesize-eval`)

Two CLI scripts that run against the live Postgres. Tested manually
against real conversation rows during the feature-test session.

| Script | Verified behavior |
|---|---|
| `scripts/synthesize-eval.py CONV=<uuid>` | Reads `app.turns` + `app.tool_calls` for the given conversation, emits a Scenario YAML at `verticals/<vertical>/scenarios/replay_<uuid-prefix>.yaml` with the correct shape (id, vertical, surface, language, user_inputs, actions, expected_tool_calls, expected_approvals, expected_mode). Verified with conversation `ce8c5c68-...` — empty conversation produces empty inputs/actions, structure correct. |
| `scripts/audit-divergences.py` | Lists audit-flagged verticals; for HVAC (`audit_transcripts: false`) correctly reports "no verticals with audit_transcripts=true; nothing to do." Behavior under audit-flagged vertical confirmed in unit tests (`test_audit.py`). |

### What this catches

- Real Postgres reads work. Real path resolution between `scripts/`,
  `core/src/`, and the runtime venv works.
- Migration drift: if you change a store dataclass, the synthesize
  script's `app.turns`/`app.tool_calls` reads will catch it.

### What this *doesn't* catch

- Behavior under sustained load (hundreds of conversations per audit
  run).

---

## 7. Live OpenAI probes

**Direct WebSocket probes from the edge container** to confirm our
wire format matches OpenAI's GA Realtime API. Used twice during
development (Phase 1 + post-Phase-6 fix verification).

### Probe 1 — initial GA-format discovery

When OpenAI rejected our first session.update with *"Model
gpt-realtime-2 is only available on the GA API"*, we probed live to
identify the new GA shape. Result: `OpenAI-Beta` header is gone in
GA; `session.type: "realtime"`, `output_modalities`, `audio.input` /
`audio.output` blocks, `semantic_vad` are required.

### Probe 2 — whisper endpoint discovery (this round)

When OpenAI rejected the whisper session.update with *"Passing a
transcription session update event to a realtime session is not
allowed"*, three URL variants were probed:

| URL | Result |
|---|---|
| `?intent=transcription` | ✅ `session.created` → `session.updated` |
| `?intent=transcription&model=gpt-realtime-whisper` | ❌ "You must not provide a model parameter for transcription sessions" |
| `/v1/realtime/transcription_sessions` | ❌ HTTP 403 Forbidden |

Confirmed that GA whisper lives at the dedicated `?intent=transcription`
endpoint and the model id flows in the session.update payload, not
the URL. Code fix landed at commit `847a382`.

### What this catches

- API drift on OpenAI's side — the code's wire format actually works
  against the live service.

### What this *doesn't* catch

- Audio quality. We send silent PCM during these probes; we don't
  validate that real spoken audio comes back as a sensible transcript.
- Real-world latency under load.

---

## 8. Browser feature tests (Claude in Chrome)

A guided session driven through the Claude-in-Chrome MCP extension.
Exercises the cockpit UI, the WebSocket bridge, and the proxied API
endpoints — i.e. the full stack end-to-end from the user-facing surface.

### What was tested

| Scenario | Verified |
|---|---|
| Login flow | Cockpit auth gate at `/`; credentials persist in sessionStorage |
| Top nav has 5 tabs | Talk / Approvals / Voicemails / Audit / Conversations all clickable, route correctly |
| Talk page UI | Talk + Notes only buttons present; tooltip on Notes-only reads "Silent transcription only — no agent persona, no tools" |
| `/voicemails` route renders | Page title + description + empty state ("No voicemails yet") |
| `/audit` route renders | Page title + description with inline `make audit` styling + empty state |
| `/conversations` list | Lists every conversation with all 3 modes (realtime2 / translate / notetaker) shown in the Mode column |
| API endpoints through Vite proxy | `/healthz`, `/v1/conversations` (incl. `?mode=` filter), `/v1/approvals`, `/v1/audits/divergences`, `/v1/verticals/hvac/business-status`, `/v1/verticals/<unknown>/business-status` (404) |
| Business-hours predicate runs in real time | At test time we crossed 5 pm Chicago; `open` flipped from `true` to `false` automatically |
| WebSocket flow `mode=realtime2` | `session.created` returned with `audit_transcripts: false` |
| WebSocket flow `mode=translate` | `session.created` returned with `audit_transcripts: false`, mode echoed |
| WebSocket flow `mode=notetaker` | `session.created` returned with mode echoed; conversation row persisted with `mode='notetaker'` (verified in psql) |
| Whisper handshake (post-fix) | `transcription_session_open` log → no `transcription_server_error_event` → `transcription_session_closed` |

### Bugs found and fixed *during* the test session

The browser test pass surfaced two real issues, both fixed and re-verified:

1. **Whisper endpoint mismatch** (`fix(whisper)` at `847a382`) —
   discovered in edge logs as
   `"Passing a transcription session update event to a realtime session
   is not allowed."`. Fixed by switching to `?intent=transcription`
   and adjusting the session.update payload (no `turn_detection`).
2. **Vite proxy capturing `/voicemails`** (`fix(frontend)` at
   `6650f51`) — the `'/voice'` proxy entry was a prefix match,
   forwarding any URL starting with `/voice` (including
   `/voicemails`) to the edge, which has no such route. Returned
   HTTP 500. Removed the proxy entry (it was dead code — the browser
   already connects to the edge directly via `VITE_EDGE_URL`).

### What this catches

- Real-stack integration: anything from the Vite proxy config to the
  cockpit's nav tabs to the OpenAI WebSocket protocol all need to
  agree, and a browser test exercises that whole chain.
- Time-of-day-sensitive predicates (`is_open_now()`) running on the
  real clock.

### What this *doesn't* catch

- Microphone permission / real audio capture. To exercise that we'd
  need either a real user granting mic permission or a Chrome
  automation flag (`--use-fake-ui-for-media-stream`). Audio capture
  and the OpenAI realtime audio loop are exercised manually and via
  unit tests against the mock fixture.
- Twilio inbound calls. To test those end-to-end we'd need a real
  Twilio number, a tunnel, and a real phone dial. Not done in this
  test pass.

---

## Coverage matrix — features × test layers

| Feature | Unit | Eval | Edge | Live probe | Browser |
|---|---|---|---|---|---|
| Realtime-2 conversational loop | ✅ | ✅ (scenarios 01–05) | ✅ (mock fixture) | — | ✅ |
| Tool dispatch + approvals | ✅ | ✅ | — | — | ✅ (UI + API) |
| Translate mode + bilingual capture | ✅ (turn-model) | ✅ (06) | ✅ (sidecar) | — | ✅ (WS opens) |
| Voicemail mode | ✅ (post_call summary) | ✅ (08) | ✅ (TwiML, routing) | — | ✅ (route + endpoint) |
| Note-taker mode | ✅ (post_call summary) | ✅ (07) | ✅ (TranscriptionSession) | — | ✅ (button + WS) |
| Audit transcripts + divergence diff | ✅ (9 tests) | — | ✅ (sidecar always-on) | — | ✅ (route renders) |
| Business hours + voicemail TwiML | ✅ (7 tests) | — | ✅ (TwiML) | — | ✅ (endpoint live) |
| Eval generation (synthesize-eval) | ✅ (5 tests + round-trip) | — | — | — | — (CLI not via browser) |
| Whisper transcription wire format | — | — | ✅ (contract pinned) | ✅ (live OpenAI) | ✅ (handshake clean) |
| GA Realtime-2 wire format | — | — | ✅ | ✅ (live OpenAI) | ✅ |
| Migration 0002 (mode CHECK widen) | ✅ (loader) | — | — | — | ✅ (insert verified) |
| Migration 0003 (audit_divergences) | — | — | — | — | ✅ (alembic head) |
| Cockpit nav + 5 routes | — | — | — | — | ✅ |
| Vite proxy `/v1` | — | — | — | — | ✅ |

---

## Gaps — what isn't tested

Honest inventory.

### 1. Real phone calls via Twilio

Nothing in the test pass exercises an actual inbound phone call. We
have unit tests for the TwiML routing logic and the business-hours
predicate, and the edge media-stream handler is type-checked, but a
real Twilio call requires:

- A Twilio account + phone number + `make tunnel` running
- A human (or a recording) on the other end of the line
- Verification that audio flows both ways through the μ-law codec

The seam is well-tested via mocks. The transport itself is
unverified end-to-end. Recommended next step: a 30-second test call
to confirm the full phone path works, documented as a manual step in
`docs/use-cases.md`.

### 2. Real microphone capture in browser

The cockpit's Talk button calls `getUserMedia({ audio: true })`,
captures via `ScriptProcessor`, encodes to base64 PCM, and sends over
WebSocket. The encoding/sending path is not unit-tested (it lives in
React component code) — it's typechecked by `tsc` and exercised by
hand. To automate, we'd need Chrome's
`--use-fake-ui-for-media-stream` flag.

### 3. Real audio through the whisper sidecar

The whisper handshake against live OpenAI is verified — the model
accepts our session.update and responds with `session.updated`. But
we haven't sent real spoken audio and verified that whisper produces
a non-trivial transcript in our `app.turns`. The audit divergence diff
is therefore tested only against synthetic transcripts.

### 4. Realtime-translate model in mid-session swap

We verify the translate session opens cleanly (browser WebSocket
test). The mid-session **flip** from realtime2 → translate (via
`session.switchModel`) is unit-tested at the JS level but hasn't been
validated end-to-end against live OpenAI.

### 5. Approval-by-voice phrase classifier with real audio

The voice-intent classifier in v1 is a transcript-based exact-phrase
matcher (the model writes the phrase down via its transcription
sub-system; we compare strings). With the whisper integration now
fixed, this could be re-tested with real audio. Currently verified
only via the eval scenarios (where the resolution path is set
explicitly in the YAML).

### 6. Concurrent / load behavior

No load testing. The system is single-tenant by design, but specific
paths that could degrade under load:

- Approval state machine under concurrent voice + cockpit
  resolution. (Has unit-test coverage for double-resolve detection
  but not at scale.)
- Trace pipeline drop-with-counter under sustained burst.
- Postgres connection pool exhaustion.

### 7. Multi-vertical deployment

We ship one vertical (`hvac`). The pack-loader code path is exercised
by it, but there's no second vertical to confirm the
"different-vertical-on-same-deployment" story holds. The seam is
clean (per-vertical pack.yaml + tools.py + scenarios), but unverified
in practice.

### 8. Cockpit on mobile / non-Chrome browsers

The frontend is built with Vite + React + Tailwind and targets modern
browsers. Tested in Chrome on Windows. Not verified on Safari,
Firefox, mobile browsers, or older WebRTC stacks.

---

## How to run everything yourself

Quick reference. Prerequisites: `make build && make up && make migrate
&& make seed-hvac`.

```bash
# 1. Backend regression
make test                      # full Python + Node suite
cd core && uv run ruff check . # lint (ruff)
cd edge && npm run typecheck   # tsc

# 2. Eval scenarios
make test-eval                 # 8 HVAC scenarios

# 3. Migration apply
make migrate
docker compose run --rm core alembic current  # confirm 0003_audit_divergences (head)

# 4. Operator scripts
make synthesize-eval CONV=<uuid>     # generate a YAML scenario from a real conv
make audit                            # diff agent vs. canonical transcripts (no-op without an audit-flagged vertical)

# 5. Live OpenAI probe (needs OPENAI_API_KEY)
cat <<'EOF' | docker compose exec -T edge node --input-type=module -
import WebSocket from 'ws';
const ws = new WebSocket(
  'wss://api.openai.com/v1/realtime?intent=transcription',
  { headers: { Authorization: 'Bearer ' + process.env.OPENAI_API_KEY } },
);
ws.on('open', () => ws.send(JSON.stringify({
  type: 'session.update',
  session: {
    type: 'transcription',
    audio: { input: { format: { type: 'audio/pcm', rate: 24000 },
                     transcription: { model: 'gpt-realtime-whisper' } } },
  },
})));
ws.on('message', m => { console.log(JSON.parse(m.toString()).type); ws.close(); });
EOF
# Expected output: session.created  session.updated

# 6. Cockpit smoke (curl)
for p in / /approvals /voicemails /audit /conversations; do
  echo "$p: $(curl -s -o /dev/null -w '%{http_code}' http://localhost:5173$p)"
done
# Expected: all HTTP 200

# 7. API smoke
curl -s http://localhost:8000/healthz | jq
curl -s http://localhost:8000/v1/verticals/hvac/business-status | jq
curl -s http://localhost:8000/v1/audits/divergences | jq
curl -s 'http://localhost:8000/v1/conversations?mode=voicemail' | jq

# 8. WebSocket smoke (paste into the cockpit's browser console)
# new WebSocket('ws://localhost:8080/v1/voice/browser?vertical=hvac&mode=notetaker')
#   .onmessage = e => console.log(e.data);
# Expected message: {"kind":"session.created","mode":"notetaker", ...}
```

---

## Where to read next

- The 13 worked examples (UI clicks · terminal · Claude Code prompts) for the same flows: [`docs/use-cases.md`](use-cases.md)
- The eval YAML schema: [`docs/eval-format.md`](eval-format.md)
- Operations runbook (incl. recovery procedures): [`docs/ops.md`](ops.md)
