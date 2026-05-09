# Voice Operations Cockpit — Documentation

A self-hostable platform that turns OpenAI's GPT-Realtime models into a working
**voice agent** — one that answers phone calls, runs on a browser cockpit,
calls real tools, and gates dangerous actions behind human approval. All three
GA Realtime models (`gpt-realtime-2`, `gpt-realtime-translate`,
`gpt-realtime-whisper`) are in active use.

This documentation is written for someone with **no prior background** in
voice AI, telephony, WebRTC, or distributed systems. Every term is defined
the first time it appears; every "obvious" technical assumption is spelled
out. If something feels too dense, jump back to [key concepts](overview/key-concepts.md).

## Where to start

| If you want to… | Read this |
|---|---|
| Understand what this thing is and why it exists | [overview/what-is-this.md](overview/what-is-this.md) |
| See realistic worked examples (UI clicks, terminal, Claude Code) | [use-cases.md](use-cases.md) |
| Look up a term you saw in code or another doc | [overview/key-concepts.md](overview/key-concepts.md) |
| See the whole architecture in one diagram | [architecture/system-design.md](architecture/system-design.md) |
| **Map each Realtime model to the features that use it** | **[reference/model-feature-map.md](reference/model-feature-map.md)** |
| See deep operational details on each Realtime model | [reference/realtime-models-in-use.md](reference/realtime-models-in-use.md) |
| Understand the GPT-Realtime model itself | [reference/gpt-realtime-2.md](reference/gpt-realtime-2.md) |
| Know how phone calls actually reach the agent | [reference/twilio-integration.md](reference/twilio-integration.md) |
| Identify every technology used and why | [reference/stack.md](reference/stack.md) |

## Concept docs

The ten OpenAI Realtime guides, mapped to where each lands in this codebase,
plus three additional concept docs for the whisper-enabled features.

| Topic | Where it lands | Read |
|---|---|---|
| voice-agents | The cockpit's primary loop — "do this for me" | [concepts/voice-agents.md](concepts/voice-agents.md) |
| realtime-conversations | Shared session memory (call → browser handoff) | [concepts/realtime-conversations.md](concepts/realtime-conversations.md) |
| realtime-webrtc | Browser cockpit | [concepts/realtime-webrtc.md](concepts/realtime-webrtc.md) |
| realtime-websocket | Phone bridge (Twilio Media Streams) | [concepts/realtime-websocket.md](concepts/realtime-websocket.md) |
| realtime-models-prompting | Persona, preambles, "stay quiet until…" | [concepts/realtime-models-prompting.md](concepts/realtime-models-prompting.md) |
| running-agents | Each turn: dispatcher + tool handlers | [concepts/running-agents.md](concepts/running-agents.md) |
| orchestration | Multi-agent seam (single-agent in v1) | [concepts/orchestration.md](concepts/orchestration.md) |
| guardrails-approvals | Spoken "yes, proceed" + cockpit queue | [concepts/guardrails-approvals.md](concepts/guardrails-approvals.md) |
| integrations-observability | One dashboard: latency, costs, traces, audit divergences | [concepts/integrations-observability.md](concepts/integrations-observability.md) |
| translate (Realtime-Translate) | Mode swap, auto + manual; bilingual capture | [concepts/translate-mode.md](concepts/translate-mode.md) |
| **voicemail mode** (whisper) | After-hours overflow handler | **[concepts/voicemail.md](concepts/voicemail.md)** |
| **note-taker mode** (whisper) | Silent dispatcher-side transcription | **[concepts/note-taker.md](concepts/note-taker.md)** |
| **audit transcripts** (whisper) | Always-on whisper sidecar + divergence diff | **[concepts/audit-transcripts.md](concepts/audit-transcripts.md)** |

## Task-oriented guides

| Task | Guide |
|---|---|
| Enable voicemail overflow for a vertical | [guides/configure-business-hours.md](guides/configure-business-hours.md) |
| Turn a real call into a regression-net eval | [guides/synthesize-eval.md](guides/synthesize-eval.md) |

## Operational docs

- [`SPEC.md`](../SPEC.md) — the platform contract.
- [`PLAN.md`](../PLAN.md) — the implementation plan, 9 phases / 41 tasks.
- [`docs/ops.md`](ops.md) — operations runbook (recovery procedures + gotchas).
- [`docs/testing.md`](testing.md) — every test layer, coverage matrix, gaps.
- [`docs/eval-format.md`](eval-format.md) — scenario eval YAML schema.
- [`README.md`](../README.md) — install, build, run.
